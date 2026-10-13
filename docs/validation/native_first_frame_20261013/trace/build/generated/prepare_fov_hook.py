"""Reproducible adapter-only modification; never writes the source benchmark."""
from pathlib import Path
import argparse,hashlib
ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);args=ap.parse_args()
base=Path(__file__).resolve().parent
source=args.base/'main.cpp'
expected='f4b27666761c582ea0a568731d0475a7806b48ee34bc5f5e92aa7175886c2b7b'
if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise ValueError('Source adapter baseline mismatch')
clock=args.base/'adapter_clock.hpp'
clock_hash='27e846a277f8eefa77f50cf82a4e331fee1235b3102a78cdace5b26633d52e77'
if hashlib.sha256(clock.read_bytes()).hexdigest()!=clock_hash:raise ValueError('External clock adapter mismatch')
(base/'adapter_clock.hpp').write_bytes(clock.read_bytes())
p=base/'main.cpp';s=source.read_text()
s=s.replace('#include <opencv2/imgcodecs.hpp>','#include <opencv2/imgcodecs.hpp>\n#include <opencv2/calib3d.hpp>\n#include <algorithm>')
s=s.replace('    bool manual_shoot=false;','''    bool manual_shoot=false;
    bool fov_initialized=false;
    std::array<double,3> operator_fov{};''')
s=s.replace('        bool detector_executed=false, frame_accepted=false, completed=false;','''        // Simulation operator fork: FOV changes require a fresh process/track state.
        const auto af=request["operator_fov"];
        if (!af || !af.IsMap() || af.size()!=3) throw std::runtime_error("operator_fov required");
        const std::array<double,3> requested_fov{af["fov_degrees"].as<double>(),af["circle_radius_x_norm"].as<double>(),af["circle_radius_y_norm"].as<double>()};
        for (double v : requested_fov) if (!std::isfinite(v)) throw std::runtime_error("Nonfinite operator FOV");
        if (requested_fov[0]<10. || requested_fov[0]>180. || requested_fov[1]<=0. || requested_fov[1]>2. || requested_fov[2]<=0. || requested_fov[2]>2.)
            throw std::runtime_error("Operator FOV outside contract");
        if (fov_initialized && requested_fov!=operator_fov) throw std::runtime_error("FOV changed: restart source process to clear tracks");
        operator_fov=requested_fov; fov_initialized=true;
        std::size_t fov_admitted2d=0, fov_rejected2d=0;
        bool detector_executed=false, frame_accepted=false, completed=false;''')
s=s.replace('                raw2d=detections.armors.size();','''                raw2d=detections.armors.size();
                // Gate actual detector output before source PnP/association/selection.
                // This sees camera pixels and calibration only, never enemy truth.
                std::erase_if(detections.armors,[&](const auto& armor) {
                    const auto point=armor.center;
                    if (!std::isfinite(point.x) || !std::isfinite(point.y) || point.x<0 || point.y<0 || point.x>=image.cols || point.y>=image.rows) return true;
                    const double dx=(point.x-image.cols*.5)/(operator_fov[1]*image.cols);
                    const double dy=(point.y-image.rows*.5)/(operator_fov[2]*image.rows);
                    if (dx*dx+dy*dy>1.+1e-12) return true;
                    std::vector<cv::Point2f> pixel{point},normalized;
                    cv::undistortPoints(pixel,normalized,cv::Mat(3,3,CV_64F,const_cast<double*>(K.data())),cv::Mat(1,5,CV_64F,const_cast<double*>(D.data())));
                    if (normalized.size()!=1 || !std::isfinite(normalized[0].x) || !std::isfinite(normalized[0].y)) return true;
                    const double angle=std::atan(std::hypot(normalized[0].x,normalized[0].y))*180./std::acos(-1.);
                    return angle>operator_fov[0]*.5+1e-12;
                });
                fov_admitted2d=detections.armors.size(); fov_rejected2d=raw2d-fov_admitted2d;''')
s=s.replace('rmcs-sync-rebuild-v2','rmcs-sim-operator-fov-v1')
s=s.replace('<< ",\\\"pose_estimated3d\\\":" << pose_estimated3d','<< ",\\\"fov_raw2d\\\":" << raw2d << ",\\\"fov_admitted2d\\\":" << fov_admitted2d << ",\\\"fov_rejected2d\\\":" << fov_rejected2d\n            << ",\\\"pose_estimated3d\\\":" << pose_estimated3d')
p.write_text(s)
