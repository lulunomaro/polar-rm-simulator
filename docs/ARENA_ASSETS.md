# Arena asset status

## Usable standalone observer

Run `python -m rm_match.arena` in the installed environment. This opens the RMUL 2026 rule-dimensioned fallback, not the full match engine. It does not change the existing engine scene, ballistic obstruction adapter, robot spawns, or rule triggers.

`rm_match/assets/arenas/rmul_2026_rules_v1_2/arena.xml` compiles as standalone MuJoCo MJCF. The separate `manifest.json` identifies each geometry, rulebook page, coordinate transform, and unverified detail. `preview.png` was rendered locally via EGL; GPU acceleration was not verified.

Verified primary dimensions are from the official RMUL 2026 V1.2.0 PDF, pages 21–25. Playable floor: 12×8 m. Highgrounds: 2×5 m, 0.2 m tall. Their inner rails: 0.15×1.8 m, another 0.2 m tall. Control zone: 3×3 m. Supply zones: 1.5×2 m. Placement is transcribed from the plan view on page22. Origin is floor centre, +x right on the plan, +y up, +z upwards. Red supply is at (-5.25,3), blue at (5.25,-3).

Each structural box has independent analytic collision. Markings are visual-only. No single concave arena mesh is handed to MuJoCo as a convex collider. Seven downward raycasts verify floor, highground and rail heights and open corridor positions. Tests also compile a composed robot scene with fixture robots explicitly relocated, without changing the harness file.

### Explicit gaps

- This geometry is newly authored from rule dimensions, not imported official CAD.
- Boundary wall outer envelope is CAD-verified (0.3 m thick, 0.42 m tall including cover), but hollow internals are replaced with a solid envelope. Friction and colours are provisional.
- Original simple visual crosses/grid stand in for official artwork and textures; RFID hardware is omitted.
- It is a 2026 UL fallback, not a verified 2027 arena or an RMUC full field.
- It is not yet connected to whole-match movement, projectile obstruction, spawn, or zone adjudication.

## Official CAD acquisition sources

Official field post: https://bbs.robomaster.com/article/814728

The post says the CAD is for reference; rules and actual event field prevail. Current RMUC CAD V2.0.0 is 1,254,821,405 bytes; older V1.2 is 993,297,750 bytes. The official RMUL CAD was downloaded and hash-verified: SHA256 `b0d380030c3d0dacf21bc53345bd3dc5c4c11763ab180f1de0b86fb0240d651c`, 1,680,693 bytes, based on V1.0 rules. STEP units are mm; world transform is `(x,z,-y)*0.001`. It has one nonconvex solid and1106 planar faces. CAD inspection confirms old highgrounds are6.5 m long; current V1.2 rule dimensions require5 m. The observer uses current5 m geometry. Do not use the unmodified CAD as current collision geometry.

A community corrected RMUL V1.2 STEP is published by Potential at https://bbs.robomaster.com/article/1639469 under CC BY-NC-SA4.0. It is not an official CAD update and must retain attribution and noncommercial/share-alike conditions if reused.

Official robot references (historical infantry, not current wheel-leg geometry):

- https://www.robomaster.com/zh-CN/products/components/detail/2711 — 2020 self-assembly infantry A, official 3D STEP link.
- https://www.robomaster.com/zh-CN/products/components/detail/1839 — 2019 AI robot, STEP/Creo/SW links; official dimensions600×450×460 mm and mass16.6 kg. Mecanum chassis and yaw/pitch gimbal.

The existence of a public CAD download does not establish unrestricted redistribution rights. This source package bundles no third-party robot CAD. Supply only assets that you have permission to use, and separately verify articulated dynamics.

No official 2027 all-robot CAD set, team-specific wheel-leg CAD, inertia, contact properties or actuation has been verified by this asset module.
