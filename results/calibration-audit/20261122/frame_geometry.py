"""Evaluate Brown geometry on both native pixel grids. No image remap is produced."""
import argparse
import json
from math import comb
from pathlib import Path

import cv2
import numpy as np

TOL_PX = 1e-5


def brown(z, D):
    k1,k2,p1,p2,k3 = D
    x,y = z.T
    s = x*x + y*y
    a = 1 + s*(k1+s*(k2+s*k3))
    b = 2*(k1+s*(2*k2+3*s*k3))
    w = np.column_stack([x*a+2*p1*x*y+p2*(s+2*x*x), y*a+2*p2*x*y+p1*(s+2*y*y)])
    jxx = a+b*x*x+2*p1*y+6*p2*x
    jxy = b*x*y+2*p1*x+2*p2*y
    jyy = a+b*y*y+2*p2*x+6*p1*y
    return w, jxx, jxy, jyy


def segment_pd(z, D):
    """Sufficient certificate J(t z)>0, 0<=t<=1, by Bernstein convex hull."""
    k1,k2,p1,p2,k3 = D
    x,y = z.T
    s = x*x+y*y
    tangent = np.array([2*p1*y+6*p2*x, 2*p1*x+2*p2*y, 2*p2*x+6*p1*y])
    ok = np.ones(len(x), dtype=bool)
    for i in range(7):
        a,b,c = (i/6)*tangent
        a, c = a+1, c+1
        for m,k in ((2,k1),(4,k2),(6,k3)):
            if m <= i:
                factor = k * comb(i,m)/comb(6,m) * s**(m//2-1)
                a += factor*(s + m*x*x)
                b += factor*(m*x*y)
                c += factor*(s + m*y*y)
        ok &= (a>0) & (a*c-b*b>0)
    return ok


def inverse(target, D, focal):
    # Damped Newton restricted to positive definite steps. Independently certify
    # the final root's connection to the axis and verify its forward error.
    z = target.copy()
    pending = np.arange(len(z))
    for _ in range(45):
        if not len(pending):
            break
        w,a,b,c = brown(z[pending],D)
        err = w-target[pending]
        det = a*c-b*b
        size = np.linalg.norm(err*focal,axis=1)
        active = (size>1e-9) & (det>0) & (a>0)
        ids = pending[active]
        if not len(ids):
            break
        step = np.column_stack([c*err[:,0]-b*err[:,1],a*err[:,1]-b*err[:,0]])[active]/det[active,None]
        left = np.arange(len(ids))
        moved = np.zeros(len(ids),dtype=bool)
        for halving in range(20):
            if not len(left):
                break
            subset = ids[left]
            trial = z[subset]-step[left]*2.**(-halving)
            v,aa,bb,cc = brown(trial,D)
            better = np.linalg.norm((v-target[subset])*focal,axis=1) < size[active][left]
            accept = (aa>0) & (aa*cc>bb*bb) & better
            z[subset[accept]] = trial[accept]
            moved[left[accept]] = True
            left = left[~accept]
        pending = ids[moved]
    w,a,b,c = brown(z,D)
    error = np.linalg.norm((w-target)*focal,axis=1)
    ok = (error <= TOL_PX) & segment_pd(z,D)
    return z, ok, error


def runs(flags):
    indices = np.flatnonzero(np.diff(np.r_[False,flags,False]))
    return [[int(a),int(b-1)] for a,b in indices.reshape(-1,2)]


def directional_upper(z, D, R):
    """Upper bound on n·F over the axis-connected branch; n is each received ray."""
    k1,k2,p1,p2,k3 = D
    tangent = np.array([p2,p1])
    n = z/np.linalg.norm(z,axis=1)[:,None]
    parallel = n @ tangent
    perpendicular = n[:,0]*p1 - n[:,1]*p2
    # rho/r lower bound on [0,R]. Complete the square in sin(theta),
    # using 1-cos(theta) >= sin(theta)^2/2 (see the accompanying report).
    min_radial = 1 + min(k1,0)*R**2 + min(k2,0)*R**4 + min(k3,0)*R**6
    denominator = min_radial/2-2*R*np.linalg.norm(tangent)
    if denominator <= 0:
        return None
    def rho(r):
        return r*(1+r*r*(k1+r*r*(k2+r*r*k3)))
    grid = np.linspace(0,R,1025)
    a,b = grid[:-1],grid[1:]
    peak = np.maximum(rho(a),rho(b))
    for root in np.roots([7*k3,5*k2,3*k1,1]):
        if abs(root.imag)<1e-10 and root.real>0:
            peak = np.maximum(peak,rho(np.clip(np.sqrt(root.real),a,b)))
    upper = np.empty(len(z))
    for start in range(0,len(z),512):
        sl = slice(start,start+512)
        proj = parallel[sl,None]
        upper[sl] = (peak + 3*np.maximum(proj*a*a,proj*b*b)).max(axis=1)
    return upper + R**3 * perpendicular**2 / denominator


def calculate(model, width, height):
    K,D = np.array(model["K"]), np.array(model["D"]).ravel()
    focal, center = K.diagonal()[:2], K[:2,2]
    y,x = np.indices((height,width))
    uv = np.column_stack([x.ravel(),y.ravel()])
    target = (uv-center)/focal
    # Work in bounded chunks, including OpenCV's projectPoints Jacobian workspace.
    masks, zs, errors, ideals, cv_errors, cv_diffs = [],[],[],[],[],[]
    for block in np.array_split(target, max(1,height//16)):
        z,ok,err = inverse(block,D,focal)
        masks.extend(ok)
        zs.extend(z)
        errors.extend(err)
        normalized = np.column_stack([block,np.ones(len(block))])
        via_cv = cv2.projectPoints(normalized,np.zeros(3),np.zeros(3),K,D)[0].reshape(-1,2)
        forward = brown(block,D)[0]
        cv_diffs.extend(np.linalg.norm(via_cv-(forward*focal+center),axis=1))
        back, branch, _ = inverse(forward,D,focal)
        ideal_error = np.linalg.norm((back-block)*focal,axis=1)
        ideals.extend(zip(branch & (ideal_error<=TOL_PX),ideal_error))
        cv_back = cv2.undistortPoints(block*focal+center,K,D).reshape(-1,2)
        cv_errors.extend(np.linalg.norm((brown(cv_back,D)[0]-block)*focal,axis=1))
    valid, zs, errors = np.asarray(masks), np.asarray(zs), np.asarray(errors)
    ideal_ok, ideal_errors = np.array(ideals).T
    valid_image = valid.reshape(height,width)
    forward,aa,bb,cc = brown(target,D)
    ideal_det = aa*cc-bb*bb
    ideal_eig = (aa+cc-np.hypot(aa-cc,2*bb))/2
    _,a,b,c = brown(zs[valid],D)
    det = a*c-b*b
    eig = (a+c-np.hypot(a-c,2*b))/2
    projected = forward*focal+center
    outside = np.any((projected<0) | (projected>[width-1,height-1]),axis=1)
    def bounds(values):
        return [float(np.min(values)),float(np.max(values))]
    edges = {"top_x": valid_image[0], "bottom_x": valid_image[-1],
             "left_y": valid_image[:,0], "right_y": valid_image[:,-1]}
    corners = {}
    for u,v in ((0,0),(width-1,0),(0,height-1),(width-1,height-1)):
        idx = v*width+u
        corners[f"{u},{v}"] = {"received_normalized_radius":float(np.linalg.norm(target[idx])),
                                 "central_root":bool(valid[idx]),
                                 "central_ideal_xy":zs[idx].tolist() if valid[idx] else None}
    audit = {"opencv":cv2.__version__, "size":[width,height], "K":K.tolist(),"D":D.tolist(),
             "tolerance_px":TOL_PX,"pixel_centers":len(target),
             "received":{"certified_root_count":int(valid.sum()),"without_verified_root_count":int((~valid).sum()),
                 "valid_roundtrip_max_px":float(errors[valid].max()),"root_det_range":bounds(det),
                 "root_min_eigenvalue_range":bounds(eig),
                 "valid_inclusive_boundary_runs":{k:runs(e) for k,e in edges.items()},
                 "invalid_x_runs_by_y":{str(y):runs(~row) for y,row in enumerate(valid_image) if not row.all()},
                 "corners":corners},
             "same_K_ideal_grid":{"forward_outside_received_count":int(outside.sum()),
                 "forward_then_inverse_pass":int(ideal_ok.sum()),"roundtrip_max_px":float(ideal_errors.max()),
                 "det_range":bounds(ideal_det),"min_eigenvalue_range":bounds(ideal_eig),
                 "forward_vs_cv_projectPoints_max_px":float(max(cv_diffs))},
             "opencv_default_inverse":{"forward_error_max_px":float(max(cv_errors)),
                 "errors_over_tolerance":int(np.sum(np.array(cv_errors)>TOL_PX))}}
    # General sufficient upper bound when radial Rayleigh upper polynomial
    # has exactly one positive zero and rho stays positive up to that radius.
    k1,k2,p1,p2,k3 = D
    tang = np.hypot(p1,p2)
    roots = np.roots([7*k3,0,5*k2,0,3*k1,6*tang,1])
    pos = [r.real for r in roots if abs(r.imag)<1e-10 and r.real>0]
    if len(pos)==1:
        r = pos[0]
        radial_zeros = np.roots([k3,k2,k1,1])
        if not any(abs(t.imag)<1e-10 and 0<t.real<=r*r for t in radial_zeros):
            bound = r*(1+r*r*(k1+r*r*(k2+r*r*k3))) + 3*tang*r*r
            beyond = np.linalg.norm(target,axis=1)>bound+1e-12
            assert not np.any(beyond & valid)
            audit["received"]["analytic_bound"] = {"central_radius_upper":float(r),
                "received_radius_upper":float(bound),"proven_outside_count":int(beyond.sum()),
                "other_unresolved_count":int(np.sum(~valid & ~beyond))}
            if (~valid).any():
                failed = target[~valid]
                support = directional_upper(failed,D,r+1e-12)
                if support is not None:
                    gap = np.linalg.norm(failed,axis=1)-support
                    audit["received"]["directional_bound"] = {
                        "proven_outside_among_without_root":int(sum(gap>1e-10)),
                        "still_unclassified":int(sum(gap<=1e-10)),
                        "minimum_normalized_gap":float(min(gap)),
                        "roundoff_margin":1e-10,"radial_intervals":1024}
    return audit


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("intrinsics",type=Path)
    p.add_argument("output",type=Path)
    args = p.parse_args()
    model = json.loads(args.intrinsics.read_text())
    output = calculate(model,*model["image_size"])
    args.output.write_text(json.dumps(output,indent=2,allow_nan=False)+"\n")
