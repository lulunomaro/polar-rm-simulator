"""Trusted Windows child lifecycle: job ownership before any child execution.

No PID-tree enumeration, taskkill, shell, or fallback. This is not a sandbox.
Only inherited stdin/stdout/stderr handles are admitted to the suspended child.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as w
import os
import subprocess
import sys
import time

class _Security(ctypes.Structure):
    _fields_=[('length',w.DWORD),('descriptor',w.LPVOID),('inherit',w.BOOL)]
class _Startup(ctypes.Structure):
    _fields_=[('cb',w.DWORD),('reserved',w.LPWSTR),('desktop',w.LPWSTR),('title',w.LPWSTR),
        ('x',w.DWORD),('y',w.DWORD),('xsize',w.DWORD),('ysize',w.DWORD),
        ('xchars',w.DWORD),('ychars',w.DWORD),('fill',w.DWORD),('flags',w.DWORD),
        ('show',w.WORD),('reserved_size',w.WORD),('reserved_bytes',ctypes.POINTER(ctypes.c_byte)),
        ('stdin',w.HANDLE),('stdout',w.HANDLE),('stderr',w.HANDLE)]
class _StartupEx(ctypes.Structure):
    _fields_=[('startup',_Startup),('attributes',w.LPVOID)]
class _ProcessInfo(ctypes.Structure):
    _fields_=[('process',w.HANDLE),('thread',w.HANDLE),('pid',w.DWORD),('tid',w.DWORD)]
class _BasicLimit(ctypes.Structure):
    _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),
        ('minimum_working',ctypes.c_size_t),('maximum_working',ctypes.c_size_t),
        ('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
class _Counters(ctypes.Structure):
    _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
class _ExtendedLimit(ctypes.Structure):
    _fields_=[('basic',_BasicLimit),('io',_Counters),('process_memory',ctypes.c_size_t),
        ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
class _Accounting(ctypes.Structure):
    _fields_=[('user_time',ctypes.c_longlong),('kernel_time',ctypes.c_longlong),
        ('period_user',ctypes.c_longlong),('period_kernel',ctypes.c_longlong),('page_faults',w.DWORD),
        ('total_processes',w.DWORD),('active_processes',w.DWORD),('terminated_processes',w.DWORD)]

def _api():
    if sys.platform!='win32':raise RuntimeError('Windows job lifecycle requires Windows')
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    declarations={
        'CreatePipe':([ctypes.POINTER(w.HANDLE),ctypes.POINTER(w.HANDLE),ctypes.POINTER(_Security),w.DWORD],w.BOOL),
        'SetHandleInformation':([w.HANDLE,w.DWORD,w.DWORD],w.BOOL),
        'CreateFileW':([w.LPCWSTR,w.DWORD,w.DWORD,ctypes.POINTER(_Security),w.DWORD,w.DWORD,w.HANDLE],w.HANDLE),
        'CreateJobObjectW':([w.LPVOID,w.LPCWSTR],w.HANDLE),
        'SetInformationJobObject':([w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD],w.BOOL),
        'AssignProcessToJobObject':([w.HANDLE,w.HANDLE],w.BOOL),
        'TerminateJobObject':([w.HANDLE,w.UINT],w.BOOL),
        'QueryInformationJobObject':([w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,w.LPVOID],w.BOOL),
        'InitializeProcThreadAttributeList':([w.LPVOID,w.DWORD,w.DWORD,ctypes.POINTER(ctypes.c_size_t)],w.BOOL),
        'UpdateProcThreadAttribute':([w.LPVOID,w.DWORD,ctypes.c_size_t,w.LPVOID,ctypes.c_size_t,w.LPVOID,w.LPVOID],w.BOOL),
        'DeleteProcThreadAttributeList':([w.LPVOID],None),
        'CreateProcessW':([w.LPCWSTR,w.LPWSTR,w.LPVOID,w.LPVOID,w.BOOL,w.DWORD,w.LPVOID,w.LPCWSTR,w.LPVOID,ctypes.POINTER(_ProcessInfo)],w.BOOL),
        'ResumeThread':([w.HANDLE],w.DWORD), 'CloseHandle':([w.HANDLE],w.BOOL),
        'WaitForSingleObject':([w.HANDLE,w.DWORD],w.DWORD),
        'GetExitCodeProcess':([w.HANDLE,ctypes.POINTER(w.DWORD)],w.BOOL),
        'TerminateProcess':([w.HANDLE,w.UINT],w.BOOL),
    }
    for name,(args,result) in declarations.items():
        f=getattr(k,name);f.argtypes=args;f.restype=result
    return k
def _checked(result):
    if not result:raise ctypes.WinError(ctypes.get_last_error())
    return result
def _assign(k,job,process):_checked(k.AssignProcessToJobObject(job,process))
class OwnedLaunchFailure(RuntimeError):
    def __init__(self,cause,status):
        super().__init__('Owned suspended launch failed: '+type(cause).__name__)
        self.cleanup_status=status

class WindowsOwnedJobProcess:
    def __init__(self,command,*,cwd,env,stop_event=None):
        import msvcrt
        if type(command) is not list or not command or any(type(v) is not str for v in command):raise ValueError('Explicit argv required')
        self.command=list(command);self.stdin=None;self.stdout=None;self.returncode=None
        self._k=_api();self._process=None;self._job=None;self.pid=None;self._assigned=False
        self.cleanup_status=None;handles=[];thread=None;attributes=None;attributes_initialized=False
        def cancelled():
            if stop_event is not None and stop_event.is_set():raise RuntimeError('Owned launch cancelled before resume')
        def transfer(handle,mode,flags):
            fd=msvcrt.open_osfhandle(int(handle),flags|os.O_BINARY);handles.remove(handle)
            try:return os.fdopen(fd,mode,buffering=0)
            except BaseException:os.close(fd);raise
        try:
            cancelled();self._job=_checked(self._k.CreateJobObjectW(None,None))
            limits=_ExtendedLimit();limits.basic.flags=0x2000 # KILL_ON_JOB_CLOSE
            _checked(self._k.SetInformationJobObject(self._job,9,ctypes.byref(limits),ctypes.sizeof(limits)))
            sa=_Security(ctypes.sizeof(_Security),None,True)
            stdin_read=w.HANDLE();stdin_write=w.HANDLE();stdout_read=w.HANDLE();stdout_write=w.HANDLE()
            _checked(self._k.CreatePipe(ctypes.byref(stdin_read),ctypes.byref(stdin_write),ctypes.byref(sa),0))
            handles.extend((stdin_read.value,stdin_write.value))
            _checked(self._k.CreatePipe(ctypes.byref(stdout_read),ctypes.byref(stdout_write),ctypes.byref(sa),0))
            handles.extend((stdout_read.value,stdout_write.value))
            _checked(self._k.SetHandleInformation(stdin_write,1,0));_checked(self._k.SetHandleInformation(stdout_read,1,0))
            null=self._k.CreateFileW('NUL',0x40000000,3,ctypes.byref(sa),3,0x80,None)
            if null==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
            handles.append(null)
            size=ctypes.c_size_t();self._k.InitializeProcThreadAttributeList(None,1,0,ctypes.byref(size))
            if not size.value:raise ctypes.WinError(ctypes.get_last_error())
            storage=ctypes.create_string_buffer(size.value);attributes=ctypes.cast(storage,w.LPVOID)
            _checked(self._k.InitializeProcThreadAttributeList(attributes,1,0,ctypes.byref(size)))
            attributes_initialized=True
            inherited=(w.HANDLE*3)(stdin_read.value,stdout_write.value,null)
            _checked(self._k.UpdateProcThreadAttribute(attributes,0,0x20002,inherited,ctypes.sizeof(inherited),None,None))
            si=_StartupEx();si.startup.cb=ctypes.sizeof(si);si.startup.flags=0x100
            si.startup.stdin=stdin_read;si.startup.stdout=stdout_write;si.startup.stderr=null;si.attributes=attributes
            block=ctypes.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(env.items(),key=lambda i:i[0].upper()))+'\0\0')
            info=_ProcessInfo();argv=ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
            cancelled()
            _checked(self._k.CreateProcessW(command[0],argv,None,None,True,
                0x4|0x400|0x80000|0x08000000,block,str(cwd),ctypes.byref(si),ctypes.byref(info)))
            self._process=info.process;thread=info.thread;self.pid=int(info.pid)
            _assign(self._k,self._job,self._process);self._assigned=True
            self.stdin=transfer(stdin_write.value,'wb',os.O_WRONLY)
            self.stdout=transfer(stdout_read.value,'rb',os.O_RDONLY)
            cancelled()
            if self._k.ResumeThread(thread)==0xFFFFFFFF:raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as exc:
            # Assignment failure is still suspended and cannot execute argv.
            errors=[];spawned=self._process is not None;reaped=False;active=0
            if self._process:
                try:
                    if self._assigned:_checked(self._k.TerminateJobObject(self._job,1))
                    else:_checked(self._k.TerminateProcess(self._process,1))
                    reaped=self._k.WaitForSingleObject(self._process,1000)==0
                    if not reaped:errors.append('suspended_process_exit_unproved')
                    active=self.active_processes()
                    if active:errors.append('failed_launch_job_not_empty')
                except Exception as cleanup_exc:errors.append('launch_cleanup:'+type(cleanup_exc).__name__);active=None
            for stream in (self.stdin,self.stdout):
                if stream is not None:stream.close()
            try:self.release_handles()
            except Exception as handle_exc:errors.append('launch_handle_close:'+type(handle_exc).__name__)
            status=dict(clean=not errors,reaped=reaped,not_spawned=not spawned,group_empty=active==0,
                active_processes=active,errors=errors,pid=self.pid,ownership='suspended_before_execute_job_kill_on_close')
            raise OwnedLaunchFailure(exc,status) from exc
        finally:
            if thread:self._k.CloseHandle(thread)
            if attributes_initialized:self._k.DeleteProcThreadAttributeList(attributes)
            for handle in handles:self._k.CloseHandle(handle)

    def poll(self):
        if self.returncode is not None:return self.returncode
        if self._process is None:raise RuntimeError('Owned process handle closed before wait')
        status=self._k.WaitForSingleObject(self._process,0)
        if status==258:return None
        if status!=0:raise ctypes.WinError(ctypes.get_last_error())
        code=w.DWORD();_checked(self._k.GetExitCodeProcess(self._process,ctypes.byref(code)))
        self.returncode=int(code.value);return self.returncode

    def wait(self,timeout=None):
        if self.returncode is not None:return self.returncode
        ms=0xFFFFFFFF if timeout is None else min(0xFFFFFFFE,max(0,int(timeout*1000)))
        result=self._k.WaitForSingleObject(self._process,ms)
        if result==258:raise subprocess.TimeoutExpired(self.command,timeout)
        if result!=0:raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def active_processes(self):
        if self._job is None:raise RuntimeError('Job handle no longer available for proof')
        info=_Accounting();_checked(self._k.QueryInformationJobObject(self._job,1,ctypes.byref(info),ctypes.sizeof(info),None))
        return int(info.active_processes)

    def cleanup(self,deadline):
        if self.cleanup_status is not None:return dict(self.cleanup_status)
        errors=[]
        try:
            _checked(self._k.TerminateJobObject(self._job,1))
            while self.active_processes() and time.perf_counter()<deadline:time.sleep(min(.005,max(0,deadline-time.perf_counter())))
            active=self.active_processes()
            if active:errors.append('owned_job_still_active')
            self.wait(timeout=max(0,deadline-time.perf_counter()))
        except Exception as exc:
            errors.append(type(exc).__name__+':'+str(exc));active=None
        self.cleanup_status=dict(clean=not errors,reaped=self.returncode is not None,
            group_empty=active==0,active_processes=active,returncode=self.returncode,errors=errors,pid=self.pid,
            ownership='suspended_before_execute_job_kill_on_close')
        return dict(self.cleanup_status)

    def release_handles(self):
        errors=[]
        for name in ('_job','_process'):
            handle=getattr(self,name,None)
            if handle:
                if self._k.CloseHandle(handle):setattr(self,name,None)
                else:errors.append(name+':'+str(ctypes.get_last_error()))
        if errors:raise RuntimeError('Owned handle close failed: '+','.join(errors))
