"""Read source-native diagnostic windows. No local training contract is issued here."""
import json
from pathlib import Path

import av
import numpy as np


class SourceEpisode:
    def __init__(self, raw, directory):
        directory=Path(directory)
        self.meta=json.loads((directory/"source.json").read_text())
        self.video=Path(raw)/self.meta["video"]
        with np.load(directory/"grid.npz",allow_pickle=False) as grid:
            self.state=grid["state"]
            self.actions=grid["future_state"]
            self.starts=grid["starts"]
            self.pts=grid["image_pts"]

    def __len__(self):
        return len(self.starts)

    def __getitem__(self, index):
        start=int(self.starts[index])
        pts=int(self.pts[start])
        with av.open(str(self.video)) as c:
            st=c.streams.video[0]
            st.codec_context.thread_count=1
            c.seek(pts,stream=st)
            for fr in c.decode(st):
                if fr.pts >= pts:
                    if fr.pts != pts:
                        raise ValueError(f"Missing source frame at PTS {pts}")
                    image=fr.to_ndarray(format="rgb24")
                    break
            else:
                raise ValueError(f"End of source stream before PTS {pts}")
        # First seven in B are the observed working side. The stored grid keeps both arms.
        return dict(state=self.state[start,:7].copy(),actions=self.actions[start:start+10,:7].copy(),
                    camera_rgb=image,prompt=self.meta["prompt"])
