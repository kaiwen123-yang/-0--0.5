# E/F complete task results

Finished: 2026-11-02T13:05:34.316735+00:00. Selected: B.

B historical full training 211/240, validation 72/75, original test 53/60 retained. New test is not used for model selection or further training.

Actual compute: {"updates": {"E": 500, "F": 500}, "autonomous_tasks": 246, "baseline_reused": 123}

Local teacher: 24 attempts, 24 complete successes. Intervention episodes are not autonomous policy successes.

|Model|Split|Slot|Full success|Median closure s|Median closure XY mm|
|---|---|---|---|---|---|
|B|train|all|25/48|4.8|12.461361447081327|
|B|train|back|14/32|7.15|14.322702798643125|
|B|train|front_left|4/8|4.025|6.357885912792677|
|B|train|front_right|7/8|4.175|7.9170301021119505|
|B|validation|all|72/75|3.95|8.32864272919409|
|B|validation|back|23/25|4.8|9.639104431617822|
|B|validation|front_left|24/25|3.85|7.633901750823254|
|B|validation|front_right|25/25|3.85|8.096633274158524|
|E_500|train|all|34/48|4.25|10.630421449700146|
|E_500|train|back|21/32|5.25|12.904448444545542|
|E_500|train|front_left|5/8|3.825|6.642601546541416|
|E_500|train|front_right|8/8|3.95|8.049135132002256|
|E_500|validation|all|67/75|3.8|7.6773375606026|
|E_500|validation|back|22/25|3.95|7.142820323707963|
|E_500|validation|front_left|21/25|3.9|7.300049663393119|
|E_500|validation|front_right|24/25|3.65|7.95195512268956|
|F_500|train|all|30/48|4.5|10.777940614746043|
|F_500|train|back|16/32|5.425000000000001|12.599191612733023|
|F_500|train|front_left|7/8|4.225|5.0937934551199415|
|F_500|train|front_right|7/8|4.3|8.806736223136626|
|F_500|validation|all|65/75|4.2|8.769887755052222|
|F_500|validation|back|18/25|4.55|10.380457604196636|
|F_500|validation|front_left|22/25|4.45|8.769887755052222|
|F_500|validation|front_right|25/25|4.05|7.598157932386252|

Closure statistics use all episodes with a closure event. No-closure counts and failure stages are in behavior_comparison.json. Interpret speed together with complete success.
Per-update loss, learning rate, sampling source, local/cumulative updates are in E/F. Both start at the same B full model/optimizer/RNG and old normalization, fixed 1e-6 and batch4.
Raw trajectories and videos use the Release queue. Experiment status, upload status and deletion status are separate.

New layouts were not evaluated because no candidate surpassed B.
