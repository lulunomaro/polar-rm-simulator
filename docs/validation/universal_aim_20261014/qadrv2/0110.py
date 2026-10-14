#!/usr/bin/env python3
"""Generate bounded diagnostic overlays; never edit recovered inputs or run NN."""
from __future__ import annotations
import argparse
from pathlib import Path

PROFILES=('first-frame-trace','request-preallocate-trace')


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Performance profile source anchor changed: '+old[:90])
    return text.replace(old,new,1)


def generate_profile(base,generated,profile,*,header_source=None):
    if profile not in PROFILES:raise ValueError('Unknown performance profile')
    base=Path(base);generated=Path(generated)
    original=base/'candidate/src/module/detector/armor_detection.cpp'
    armor=original.read_text(encoding='utf-8');main=(generated/'main.cpp').read_text(encoding='utf-8')
    armor='#include "first_frame_trace.hpp"\n'+armor
    armor=once(armor,'        openvino_model   = model.compile(openvino_core, config.model_location);',
        '        {\n            rmcs::first_frame_trace::Scope phase("model_compile",true);\n'
        '            rmcs::first_frame_trace::configure_inference_threads(openvino_core);\n'
        '            openvino_model = model.compile(openvino_core, config.model_location);\n'
        '            rmcs::first_frame_trace::verify_inference_threads(openvino_model);\n        }\n'
        '        rmcs::first_frame_trace::report_compiled_model(openvino_model);')
    allocation='''        if (!cached_ready) {
            cached_input_tensor = ov::Tensor {
                ov::element::u8,
                input_layout.shape(input_dimensions),
            };
            cached_request = openvino_model.create_infer_request();
            cached_ready   = true;
        }'''
    armor=once(armor,allocation,'        if (!cached_ready) allocate_cached_request(false);')
    helper='''    auto allocate_cached_request(bool startup) -> void {
        {
            rmcs::first_frame_trace::Scope phase("tensor_create",startup);
            cached_input_tensor = ov::Tensor {
                ov::element::u8,
                input_layout.shape(input_dimensions),
            };
        }
        {
            rmcs::first_frame_trace::Scope phase("request_create",startup);
            cached_request = openvino_model.create_infer_request();
        }
        cached_ready = true;
    }

'''
    armor=once(armor,'    auto generate_openvino_request(const cv::Mat& origin_mat) noexcept',
        helper+'    auto generate_openvino_request(const cv::Mat& origin_mat) noexcept')
    if profile=='request-preallocate-trace':
        armor=once(armor,'        cached_ready     = false;',
            '        cached_ready     = false;\n        {\n            rmcs::first_frame_trace::Scope phase("request_preallocate",true);\n            allocate_cached_request(true);\n        }')
    armor=once(armor,'        if (origin_mat.empty()) [[unlikely]] {',
        '        rmcs::first_frame_trace::Scope phase("generate_request");\n        if (origin_mat.empty()) [[unlikely]] {')
    armor=once(armor,'        {\n            adapt_scaling = std::min',
        '        {\n            rmcs::first_frame_trace::Scope phase("resize");\n            adapt_scaling = std::min')
    armor=once(armor,'        cached_request.set_input_tensor(cached_input_tensor);',
        '        {\n            rmcs::first_frame_trace::Scope phase("input_attach");\n'
        '            cached_request.set_input_tensor(cached_input_tensor);\n        }')
    for accumulator,phase in [('infer','infer'),('post','post_nms')]:
        anchor='            ScopedNs t(g_prof.'+accumulator+'_ns);'
        armor=once(armor,anchor,'            rmcs::first_frame_trace::Scope phase("'+phase+'");\n'+anchor)
    main='#include "first_frame_trace.hpp"\n'+main
    runner='        Runner runner(std::filesystem::absolute(argv[1]),std::filesystem::absolute(config));'
    main=once(main,runner,'        rmcs::first_frame_trace::configure_opencv_threads();\n'+runner)
    main=once(main,'        const auto control_ns=request["control_time_ns"].as<std::int64_t>();',
        '        rmcs::first_frame_trace::FirstTick diagnostic_tick;\n'
        '        const auto control_ns=request["control_time_ns"].as<std::int64_t>();')
    exposure='            const auto exposure_ns=f["exposure_timestamp_ns"].as<std::int64_t>();'
    main=once(main,exposure,exposure+'\n            diagnostic_tick.start(f["frame_id"].as<std::int64_t>(),exposure_ns,control_ns);')
    main=once(main,'                auto image_path=required_file(im,"path");',
        '                cv::Mat image;\n                {\n                rmcs::first_frame_trace::Scope phase("actual_bgr_read");\n'
        '                auto image_path=required_file(im,"path");')
    main=once(main,'                cv::Mat image;\n                if (image_path.extension()',
        '                if (image_path.extension()')
    validation='                if (image.empty() || image.cols!=1440 || image.rows!=1080) throw std::runtime_error("Invalid decoded frame dimensions");'
    main=once(main,validation,validation+'\n                }')
    detect='                auto detections=detector.detect(image); detector_executed=true; ++inference_calls;'
    main=once(main,detect,'                auto detections=[&] { rmcs::first_frame_trace::Scope phase("detector"); return detector.detect(image); }(); detector_executed=true; ++inference_calls;')
    pose='                auto armors3d=estimator.estimate_armor(detections.armors,image); pose_estimated3d=armors3d.size();'
    main=once(main,pose,'                auto armors3d=[&] { rmcs::first_frame_trace::Scope phase("pose_estimation"); return estimator.estimate_armor(detections.armors,image); }(); pose_estimated3d=armors3d.size();')
    main=once(main,'                tracker->clean(); tracker->store(detections.armors); tracker->store(armors3d);',
        '                Trackable::Unique incoming;\n                {\n                rmcs::first_frame_trace::Scope phase("tracker");\n'
        '                tracker->clean(); tracker->store(detections.armors); tracker->store(armors3d);')
    main=once(main,'                auto incoming=tracker->execute(exposure);',
        '                incoming=tracker->execute(exposure);\n                }')
    control='        auto control=safe_control_tick(*fire,current,state,results.shoot_allowed());'
    main=once(main,control,'        auto control=[&] { rmcs::first_frame_trace::Scope phase("control"); return safe_control_tick(*fire,current,state,results.shoot_allowed()); }();')
    main=once(main,'        const double age=current ?',
        '        rmcs::first_frame_trace::Scope phase_serialize("stdout_serialize");\n        const double age=current ?')
    template=Path(header_source or base/'overlays/first_frame_trace.hpp').read_text(encoding='utf-8')
    if template.count('@PROFILE@')!=1:raise ValueError('Trace header profile anchor changed')
    (generated/'first_frame_trace.hpp').write_bytes(template.replace('@PROFILE@',profile).encode())
    (generated/'armor_detection_profile.cpp').write_bytes(armor.encode())
    (generated/'main.cpp').write_bytes(main.encode())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True);parser.add_argument('--generated',type=Path,required=True)
    parser.add_argument('--profile',choices=PROFILES,required=True)
    args=parser.parse_args();generate_profile(args.base,args.generated,args.profile)


if __name__=='__main__':main()
