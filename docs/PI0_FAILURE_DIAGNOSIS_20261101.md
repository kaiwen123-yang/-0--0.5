# Pi0 four-failure diagnosis protocol

Authorized 2026-11-01: diagnose alignment, grasp retention, and reaction after a drop; propose the next training stage from evidence. No new optimizer updates, full-dataset training, or hardware commands are authorized by this diagnostic run.

The frozen input is Pi0 six-demo checkpoint 2010 and its twelve final episodes (base seeds 42 and 43). Four failed task identities are layout 100 red/blue and layout 101 green/blue. The two successful task identities remain positive controls. The original six teacher demonstrations are the physical feasibility and action-interface controls. Original results are retained.

First reproduce all twelve stored physical trajectories from their real executed commands and replay the six teacher demonstrations. Compare state trajectories and original full-task success, then measure two-finger contact forces, object offset in the gripper frame, gripper command/feedback, arm tracking, drops, and subsequent low/open reapproaches. These are physics diagnostics, not new autonomous-policy success results. MuJoCo 3.2.3 state/force API: https://mujoco.readthedocs.io/en/3.2.3/APIreference/APIfunctions.html

After reproduction, use narrowly controlled probes to distinguish:

1. Grasp acquisition and alignment error: a correct teacher grasp before policy takeover should improve downstream outcomes if initial alignment is the main bottleneck.
2. Retention versus dynamic motion: from the same acquired grasp, compare recorded movement with a three-second stationary closed-gripper hold; a friction change is a diagnostic sensitivity probe, never a benchmark modification.
3. Prediction error on demonstrated states versus accumulated closed-loop error: query fixed teacher observations and compare predicted joint targets and gripper width to the real teacher commands.
4. Post-drop behavior and data coverage: inspect genuine failures and paired observations; distinguish measured reaction from the absence of recovery examples in the scripted training data.

Teacher-prefix or modified-physics outcomes are labelled interventions and excluded from autonomous success rates. A two-second complete-task hold remains the success criterion. Each completed stage is pushed to GitHub with its command and compact results. Model, training data, split, reward/success conditions and original simulator source remain fixed.

The next-round plan will explicitly separate increased data coverage (120 demonstrations / 32,160 starts) from optimization budget (8,040 updates per start-epoch at batch 4). A 120-demo long run is a candidate, not a proven repair or an automatically launched job. Diagnosis determines whether it can proceed directly or needs data/control changes first.
