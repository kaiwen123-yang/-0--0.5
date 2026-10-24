"""Verify appended release videos and local links in the expanded Piper gallery."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
from urllib.parse import unquote,urlsplit

import mujoco
import numpy as np


class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.videos=0
    def handle_starttag(self,tag,attrs):
        self.videos+=tag=='video'
        self.links.extend(value for key,value in attrs if key in ('src','href'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',type=Path,required=True)
    args=parser.parse_args();root=args.campaign.resolve();reports=[]
    for path in sorted(root.glob('pi*-*/release-check.json')):
        run=path.parent
        for check in json.loads(path.read_text()):
            if 'video' not in check:continue
            folder=(run/check['source_trajectory']).parent
            saved=np.load(folder/'release-check-states.npz',allow_pickle=False)
            assert len(saved['qpos'])==len(saved['success'])==100
            model=mujoco.MjModel.from_xml_path(str(folder/'scene.xml'));data=mujoco.MjData(model)
            cam=model.camera('robot0_panorama').id
            geoms=[i for i in range(model.ngeom) if (model.geom(i).name or '').startswith(('robot0_','gripper0_')) and model.geom_group[i]==1]
            tan=np.tan(np.deg2rad(model.cam_fovy[cam])/2);maximum=0.
            for q in saved['qpos']:
                data.qpos[:]=q;mujoco.mj_forward(model,data)
                centers=(data.geom_xpos[geoms]-data.cam_xpos[cam])@data.cam_xmat[cam].reshape(3,3)
                radii=model.geom_rbound[geoms];depths=-centers[:,2]-radii
                assert np.all(depths>0)
                extent=np.column_stack(((np.abs(centers[:,0])+radii)/(depths*tan*(1280/720)),(np.abs(centers[:,1])+radii)/(depths*tan)))
                maximum=max(maximum,float(extent.max()))
            assert maximum<1
            for name,frames in [('release-check.mp4',101),('panorama-with-release.mp4',check['policy_video_frames']+101)]:
                video=folder/name
                stream=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,nb_frames,avg_frame_rate','-of','json',str(video)],text=True))['streams'][0]
                assert [stream['width'],stream['height']]==[1280,720] and stream['avg_frame_rate']=='20/1'
                assert int(stream['nb_frames'])==frames,(video,stream,frames)
                subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(video),'-f','null','-'],check=True,stdout=subprocess.DEVNULL,timeout=60)
                reports.append({'video':str(video.relative_to(root)),'frames':frames,'max_robot_projected_extent':maximum,
                                'sha256':hashlib.sha256(video.read_bytes()).hexdigest()})
    parser=Links();parser.feed((root/'index.html').read_text())
    for value in parser.links:
        url=urlsplit(value)
        if url.scheme or url.netloc or not url.path:continue
        assert (root/unquote(url.path)).exists(),value
    summary={'status':'passed','supplementary_video_files':len(reports),'gallery_video_elements':parser.videos,
             'local_gallery_links_checked':len(parser.links),'full_decode':True,'whole_robot_in_release_frames':True,'artifacts':reports}
    (root/'supplementary-validation.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({key:value for key,value in summary.items() if key!='artifacts'}))


if __name__=='__main__':main()
