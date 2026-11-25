"""Optional loopback-only HTTP relay for a D57 route with slow Hub CDN access.
Pass remote source locks on stdin. Only exact pinned files can be requested.
The relay holds network buffers in RAM and does not cache source files.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import sys
import urllib.request
from urllib.parse import quote, unquote, urlsplit

locks=json.load(sys.stdin)
allowed=set()
for source in locks:
    slug=("datasets/" if source["kind"]=="datasets" else "")+source["repo"]
    for file in source["files"]:
        allowed.add("/"+slug+"/resolve/"+source["sha"]+"/"+file["rfilename"])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        name=unquote(urlsplit(self.path).path)
        if name not in allowed:
            self.send_error(404)
            return
        headers={"User-Agent":"piper-data-audit/1.0"}
        if self.headers.get("Range"):
            headers["Range"]=self.headers["Range"]
        req=urllib.request.Request("https://huggingface.co"+quote(name),headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=60) as resp:
                self.send_response(resp.status)
                for key in ("Content-Range","Content-Length","Content-Type"):
                    if resp.headers.get(key):
                        self.send_header(key,resp.headers[key])
                self.end_headers()
                shutil.copyfileobj(resp,self.wfile,256*1024)
        except (OSError,ValueError):
            self.close_connection=True

    def log_message(self,*args):
        pass


if __name__=="__main__":
    ThreadingHTTPServer(("127.0.0.1",int(sys.argv[1])), Handler).serve_forever()
