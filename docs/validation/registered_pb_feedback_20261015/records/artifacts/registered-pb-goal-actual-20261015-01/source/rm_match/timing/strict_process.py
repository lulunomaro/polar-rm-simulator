"""Strict transport for the newly rebuilt source, without invented frame labels."""
import json
import select
from rm_match.integrations.rmcs_process import RMCSProcess

class StrictProcess(RMCSProcess):
    def control(self,packet):
        request={"control_time_ns":packet["control_time_ns"],"time_s":packet["control_time_ns"]/1e9,"frame":packet["frame"]}
        if self.process.poll() is not None:raise RuntimeError(f"Source process exited {self.process.returncode}")
        self.process.stdin.write(json.dumps(request,allow_nan=False)+"\n");self.process.stdin.flush()
        ready,_,_=select.select([self.process.stdout],[],[],self.timeout)
        if not ready:raise TimeoutError("Real source timed out; no fallback")
        line=self.process.stdout.readline()
        if not line:raise RuntimeError("Real source closed stdout")
        result=json.loads(line)
        if result.get("status")!="ok" or abs(result.get("time_s",-999)-request["time_s"])>1e-9:
            raise ValueError("Invalid source status/time: "+str(result))
        if result.get("runner_identity")!="rmcs-sync-rebuild-v2" or result.get("direction_frame")!="world":
            raise ValueError("Source adapter identity/coordinate-frame mismatch")
        if type(result.get("clock_time_ns")) is not int or result["clock_time_ns"]!=packet["control_time_ns"]:
            raise ValueError("Source simulation clock differs from exact integer control timestamp")
        if type(result.get("should_shoot")) is not bool:raise ValueError("Missing explicit source fire permission")
        if type(result.get("tracking")) is not bool:raise ValueError("Missing explicit source tracking permission")
        # This adapter's documented permission is the source's actual should_track.
        # Preserve every source field; only add common envelope/permission aliases.
        return {**result,"episode":packet["episode"],"control_time_ns":packet["control_time_ns"],
                "should_control":result["tracking"]}
