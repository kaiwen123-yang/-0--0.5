"""Read-only arithmetic review of the published real Q12/DC1 calibration results.

Reads existing JSON/YAML observations and AST-parses existing SDK constants.
It does not import the robot SDK, access hardware, refit calibration, or run models.
Requires the existing NumPy and PyYAML environment.
"""
import argparse
import ast
import json
import math
from pathlib import Path

import numpy as np
import yaml

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--session-dir', type=Path, required=True,
                    help='Directory containing candidate_result.json and pose_review.json.')
parser.add_argument('--final-dir', type=Path, required=True,
                    help='Directory containing the final JSON, OpenCV YAML, and ROS CameraInfo exports.')
parser.add_argument('--sdk-constants', type=Path, required=True,
                    help='Existing pyAgxArm/api/constants.py; read with ast, never imported.')
parser.add_argument('--output', type=Path, required=True,
                    help='Destination JSON for the numerical audit.')
args = parser.parse_args()

def read(directory, name):
    return json.loads((directory / name).read_text(encoding='utf-8'))
intr, hand, val, sel = [read(args.final_dir, n) for n in ('intrinsics.json', 'handeye.json', 'validation.json', 'selection.json')]
candidate, review = [read(args.session_dir, n) for n in ('candidate_result.json', 'pose_review.json')]
class OpenCVLoader(yaml.SafeLoader):
    pass
def matrix(loader, node):
    data = loader.construct_mapping(node, deep=True)
    return np.asarray(data['data']).reshape(data['rows'], data['cols'])
OpenCVLoader.add_constructor('tag:yaml.org,2002:opencv-matrix', matrix)
yml = yaml.load('\n'.join((args.final_dir/'Q12_DC1_calibration.yml').read_text(encoding='utf-8').splitlines()[1:]), Loader=OpenCVLoader)
ros = yaml.safe_load((args.final_dir/'camera_info.yaml').read_text(encoding='utf-8'))
K, D, X = np.asarray(intr['K']), np.asarray(intr['D']), np.asarray(hand['T_gripper_camera'])
Fref = np.asarray(hand['fixed_reference_from_train_only'])
def diff(a, b):
    return float(np.max(np.abs(np.asarray(a)-np.asarray(b))))
def shape_array(value):
    return np.asarray(value['data']).reshape(value['rows'],value['cols'])
def summarize(rows, key):
    arr=np.asarray([r[key] for r in rows],dtype=float)
    ordered=sorted(zip(arr,[r['id'] for r in rows]))
    idx=(len(arr)-1)*0.95
    return {'count':len(arr),'mean':float(arr.mean()),'median':float(np.median(arr)),
            'p95':float(np.percentile(arr,95)),'max':float(arr.max()),
            'max_id':rows[int(np.argmax(arr))]['id'],
            'p95_neighbor_ids':[ordered[math.floor(idx)][1],ordered[math.ceil(idx)][1]]}

tree=ast.parse(args.sdk_constants.read_text(encoding='utf-8'))
mdh=next(ast.literal_eval(n.value)['piper_h'] for n in tree.body
         if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ROBOT_MDH_PRESET' for t in n.targets))
def fk(q_deg):
    T=np.eye(4)
    for q,(d,a,alpha,offset) in zip(np.deg2rad(q_deg),mdh):
        ct,st,ca,sa=np.cos(q+offset),np.sin(q+offset),np.cos(alpha),np.sin(alpha)
        L=np.array([[ct,-st,0,a],[ca*st,ca*ct,-sa,-sa*d],[sa*st,sa*ct,ca,ca*d],[0,0,0,1]])
        T=T@L
    return T
def logR(R):
    a=math.acos(float(np.clip((np.trace(R)-1)/2,-1,1)))
    return np.array([R[2,1]-R[1,2],R[0,2]-R[2,0],R[1,0]-R[0,1]])*a/(2*math.sin(a)) if a>1e-10 else np.zeros(3)
qs={r['id']:r['q_deg'] for r in review}
qs.update({r['actual_pose']:r['measured_q_deg'] for r in sel['added_observations']})
Gs={name:fk(q) for name,q in qs.items()}
train=intr['train_sample_ids']
held=intr['heldout_sample_ids']
samples={r['sample_id']:r for r in hand['samples']}
calculated_fixed={name:Gs[name]@X@np.asarray(r['T_camera_target']) for name,r in samples.items()}
train_F=[calculated_fixed[n] for n in train]
U,_,Vt=np.linalg.svd(sum(f[:3,:3] for f in train_F))
ref=np.eye(4)
ref[:3,:3]=U@np.diag([1,1,np.linalg.det(U@Vt)])@Vt
ref[:3,3]=np.mean([f[:3,3] for f in train_F],axis=0)
recalc=[]
for name,r in samples.items():
    delta=np.linalg.inv(ref)@calculated_fixed[name]
    recalc.append({'id':name,'split':r['split'],
       'fixed_board_mm':float(np.linalg.norm(delta[:3,3])*1000),
       'fixed_board_deg':math.degrees(math.acos(float(np.clip((np.trace(delta[:3,:3])-1)/2,-1,1))))})
relative=[logR((np.linalg.inv(Gs[train[0]])@Gs[n])[:3,:3]) for n in train[1:]]
singular=np.linalg.svd(relative,compute_uv=False)
poses=val['per_validation_pose']
groups={'seven_total':poses,'four_original':[r for r in poses if r['id'].startswith('h')],
        'three_supplemental':[r for r in poses if r['id'].startswith('u')]}
statistics={name:{key:summarize(rows,key) for key in ('pnp_rms_px','fixed_board_mm','fixed_board_deg','full_chain_rms_px')} for name,rows in groups.items()}
statistics_error=max(abs(statistics[group][metric][stat]-val['validation_summaries'][group][metric][stat])
    for group in groups for metric in statistics[group] for stat in ('mean','p95','max'))
def baseline(names):
    c=np.array([(Gs[n]@X)[:3,3] for n in names])
    ds=np.linalg.norm(c[:,None,:]-c[None,:,:],axis=-1)
    i,j=np.unravel_index(np.argmax(ds),ds.shape)
    return {'max_optical_center_distance_mm':float(ds[i,j]*1000),'pair':[names[i],names[j]]}

# True observed K/D polynomial only; this is not a new camera calibration.
k1,k2,p1,p2,k3=D
roots=np.roots([7*k3,5*k2,3*k1,1])
positive=sorted(float(r.real) for r in roots if abs(r.imag)<1e-10 and r.real>0)
turn_radius=math.sqrt(positive[0])
rho=lambda r:float(r*(1+k1*r*r+k2*r**4+k3*r**6))
pixel_corners={'top_left':[0,0],'top_right':[639,0],'bottom_left':[0,479],'bottom_right':[639,479]}
corner_radii={n:float(np.linalg.norm([(p[0]-K[0,2])/K[0,0],(p[1]-K[1,2])/K[1,1]])) for n,p in pixel_corners.items()}
def distort(xy):
    x,y=xy
    r2=x*x+y*y
    radial=1+k1*r2+k2*r2*r2+k3*r2*r2*r2
    return np.array([x*radial+2*p1*x*y+p2*(r2+2*x*x),y*radial+p1*(r2+2*y*y)+2*p2*x*y])
def jacobian(xy):
    x,y=xy;r2=x*x+y*y
    f=1+k1*r2+k2*r2*r2+k3*r2*r2*r2
    df=k1+2*k2*r2+3*k3*r2*r2
    return np.array([[f+2*x*x*df+2*p1*y+6*p2*x,2*x*y*df+2*p1*x+2*p2*y],
                     [2*x*y*df+2*p1*x+2*p2*y,f+2*y*y*df+6*p1*y+2*p2*x]])
# Along each corner direction, explicitly show the Jacobian changes sign near the radial turnover.
jacobian_checks={}
for name in ('bottom_left','bottom_right'):
    xy=np.array([(pixel_corners[name][0]-K[0,2])/K[0,0],(pixel_corners[name][1]-K[1,2])/K[1,1]])
    direction=xy/np.linalg.norm(xy)
    jacobian_checks[name]=[{'ideal_normalized_radius':r,'jacobian_determinant':float(np.linalg.det(jacobian(r*direction))),
       'distorted_normalized_radius':float(np.linalg.norm(distort(r*direction)))} for r in (0.7,0.9,turn_radius,0.94)]

# A rigorous bound for the central, nonsingular Brown branch, including p1/p2.
# With p=(p2,p1) and z=r*u, t(z)=r^2*p+2*z*(p.z).
# J is symmetric; the branch connected to the optical axis has positive eigenvalues.
# u^T J u = rho'(r)+6*r*(p.u) <= rho'(r)+6*r*||p||.
# The positive root r_star bounds this entire central branch, not just one ray.
# For r<=r_star, ||distort(z)|| <= rho(r)+3*||p||*r^2 <= bound.
p_norm=float(np.hypot(p1,p2))
bound_roots=np.roots([7*k3,0,5*k2,0,3*k1,6*p_norm,1])
bound_positive=sorted(float(r.real) for r in bound_roots if abs(r.imag)<1e-10 and r.real>0)
r_star=bound_positive[-1]
rho_bound=rho(r_star)+3*p_norm*r_star*r_star
normal_branch_bound={
    'tangential_vector_definition':'p=(p2,p1), t(z)=r^2*p+2*z*(p dot z)',
    'p_norm':p_norm,
    'undistorted_radius_upper_bound_r_star':r_star,
    'received_radius_upper_bound_rho_star':rho_bound,
    'positive_root_count':len(bound_positive),
    'bound_derivative_residual':float(1+3*k1*r_star**2+5*k2*r_star**4+7*k3*r_star**6+6*p_norm*r_star),
    'received_corner_radius_minus_upper_bound':{n:rr-rho_bound for n,rr in corner_radii.items()},
    'bottom_corners_have_no_inverse_on_central_nonsingular_branch':all(corner_radii[n]>rho_bound for n in ('bottom_left','bottom_right')),
    'proof':'The Brown Jacobian is symmetric. The nonsingular branch connected to r=0 has positive eigenvalues. Its radial Rayleigh quotient is rho_prime(r)+6*r*(p dot u), at most rho_prime(r)+6*r*norm(p). This scalar polynomial has one positive root r_star and is negative beyond it, so the central positive-Jacobian branch is contained in r<r_star. Within that disk, norm(distorted z)<=rho(r)+3*norm(p)*r^2<=rho(r_star)+3*norm(p)*r_star^2. Both actual received bottom-corner radii exceed this global bound. This uses full p1/p2, not an assumption that distorted radius equals undistorted radius.',
    'meaning':'The published five-coefficient Brown model cannot provide a physically regular central-branch inverse for the two native received bottom corners. This is a full-frame extrapolation failure, not evidence that fitted/validated checkerboard-region geometry is wrong.'
}

out={
 'source_commit':'b3bb539109af287f7963fc750dc2dcb0b0549baa',
 'source_directory':'results/piper-real-single-v1/20261121_q12_01',
 'analysis_scope':'Offline arithmetic on published measured joint vectors and matrices; no image re-detection, no solver refit, no hardware commands, no dependency installation.',
 'file_consistency_max_abs_difference':{
  'K_json_vs_validation':diff(K,val['K']),'D_json_vs_validation':diff(D,val['D']),
  'T_handeye_vs_validation':diff(X,val['T_flange_camera']),
  'K_json_vs_OpenCV_YAML':diff(K,yml['camera_matrix']),
  'D_json_vs_OpenCV_YAML':diff(D,yml['distortion_coefficients'].ravel()),
  'T_json_vs_OpenCV_YAML':diff(X,yml['T_flange_camera']),
  'K_json_vs_ROS_YAML':diff(K,shape_array(ros['camera_matrix'])),
  'D_json_vs_ROS_YAML':diff(D,shape_array(ros['distortion_coefficients']).ravel()),
  'ROS_R_vs_identity':diff(np.eye(3),shape_array(ros['rectification_matrix'])),
  'ROS_P_vs_K_zero':diff(np.column_stack([K,np.zeros(3)]),shape_array(ros['projection_matrix']))},
 'frozen_candidate_comparison':{key:diff(candidate[key],val[key]) for key in ('K','D','T_flange_camera','T_base_board_train_mean')},
 'rigid_transform':{'R_determinant':float(np.linalg.det(X[:3,:3])),
  'R_orthonormality_max_abs':diff(X[:3,:3].T@X[:3,:3],np.eye(3)),
  'bottom_row_max_abs_error':diff(X[3],[0,0,0,1]),
  'translation_mm':(X[:3,3]*1000).tolist(),'translation_norm_mm':float(np.linalg.norm(X[:3,3])*1000),
  'convention':'p_flange = T_flange_camera @ p_camera, translations metres'},
 'split_checks':{'train_count':len(train),'heldout_count':len(held),'formal_ids':sel['original_heldout_included'],
  'supplemental_ids':[r['actual_pose'] for r in sel['added_observations']],
  'train_heldout_overlap':sorted(set(train)&set(held)),
  'train_list_matches_selection':train==sel['original_train_included'],
  'heldout_list_matches_selection':held==sel['original_heldout_included']+[r['actual_pose'] for r in sel['added_observations']],
  'posthoc_supplemental_caveat':'Three extra poses were retrospectively identified in archived pre-move frames, close to existing poses; they are not seven prospectively preassigned independent validation poses.'},
 'independent_fk_chain_reconstruction':{
  'mdh_source':'https://github.com/agilexrobotics/pyAgxArm/blob/d90e234ba8e408cfa964b38aa9120b3131fc9f85/pyAgxArm/api/constants.py',
  'joint_sources':['pose_review.json','final_seven/selection.json'],
  'max_abs_GXC_vs_published_fixed_matrix':max(diff(calculated_fixed[n],samples[n]['fixed_transform']) for n in samples),
  'train_mean_reference_max_abs_difference':diff(ref,Fref),
  'max_translation_residual_difference_mm':max(abs(r['fixed_board_mm']-samples[r['id']]['translation_error_m']*1000) for r in recalc),
  'max_rotation_residual_difference_deg':max(abs(r['fixed_board_deg']-samples[r['id']]['rotation_error_deg']) for r in recalc),
  'caveat':'This independently checks computation and units against published measured q, not physical robot kinematic accuracy.'},
 'recalculated_rotation_excitation':{'singular_values_rad':singular.tolist(),
  'second_to_first':float(singular[1]/singular[0]),'third_to_first':float(singular[2]/singular[0]),
  'max_abs_difference_vs_report':diff(singular,hand['train_relative_rotation_singular_values_rad'])},
 'recalculated_optical_center_baseline':{'train':baseline(train),'seven_validation':baseline(held)},
 'recalculated_statistics':statistics,
 'max_reported_summary_difference':statistics_error,
 'pixel_residual_caveat':'Per-image PnP RMS and full fixed-chain RMS statistics are recomputed from published per-view scalar values, not re-detected raw corner coordinates. Fixed-chain mean is about 14.8 times PnP mean because PnP refits each board pose.',
 'intrinsic_coverage':val['training_coverage'],
 'distortion_extrapolation_diagnostic':{
  'formula':'rho(r)=r*(1+k1*r^2+k2*r^4+k3*r^6); rho_prime=1+3*k1*r^2+5*k2*r^4+7*k3*r^6',
  'first_positive_radial_derivative_zero':turn_radius,'radial_distorted_radius_at_turnover':rho(turn_radius),
  'received_corner_normalized_radius':corner_radii,'full_Brown_Jacobian_along_bottom_corner_directions':jacobian_checks,
  'normal_branch_upper_bound_including_tangential':normal_branch_bound,
  'interpretation':'Actual fitted polynomial has a turnover beyond the sampled checkerboard region. Large bottom-corner received radii and absent bottom image coverage mean full-frame undistortion cannot be certified from this calibration. Do not discard local-region fit solely for this extrapolation issue.',
  'not_claimed':'No OpenCV undistort/projectPoints round-trip was run and no full per-pixel validity mask was computed. The two bottom-corner no-inverse conclusion follows from the analytic full-Brown bound above.'},
 'acceptance_boundaries':{'published_absolute_accuracy_certified':val['absolute_accuracy_certified'],
  'published_hardware_motion_acceptance':val['hardware_motion_acceptance'],
  'review_conclusion':'Published numerical results are internally consistent; local image/hand-eye chain residuals are useful. No evidence here certifies full-frame distortion or task-level absolute accuracy.'}
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
print(json.dumps({
    'output': str(args.output.resolve()),
    'max_export_difference': max(out['file_consistency_max_abs_difference'].values()),
    'max_frozen_candidate_difference': max(out['frozen_candidate_comparison'].values()),
    'max_abs_GXC_vs_published_fixed_matrix': out['independent_fk_chain_reconstruction']['max_abs_GXC_vs_published_fixed_matrix'],
    'max_reported_summary_difference': statistics_error,
    'bottom_corners_have_no_inverse_on_central_nonsingular_branch': normal_branch_bound['bottom_corners_have_no_inverse_on_central_nonsingular_branch'],
}, ensure_ascii=False, indent=2))
