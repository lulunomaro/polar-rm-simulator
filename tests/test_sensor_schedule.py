from rm_match.sensor_schedule import SensorSchedule

def test_capture_control_and_processing_are_separate():
    s=SensorSchedule(); captures=[];controls=[];processed=[];latest=None
    for step in range(2000):
        if s.capture(step):captures.append(step);latest=step
        if s.control(step):controls.append(step)
        if s.process(step):processed.append((step,latest))
    assert len(captures)==80 and len(controls)==100 and len(processed)==36
    assert set(b-a for a,b in zip(captures,captures[1:]))=={25}
    assert max(delivered-captured for delivered,captured in processed)<=24
    assert len({capture for _,capture in processed})==36

def test_ideal_eighty_profile_delivers_all_unique_frames():
    s=SensorSchedule(detector_hz=80);latest=None;processed=[]
    for step in range(2000):
        if s.capture(step):latest=step
        if s.process(step):processed.append((step,latest))
    assert len(processed)==80 and len({c for _,c in processed})==80
    assert max(t-c for t,c in processed)==15
