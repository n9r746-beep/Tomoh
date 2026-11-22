"""Private server-to-server Supabase Storage relay; no secrets reach the browser."""
import json
import os
import urllib.request
from pathlib import Path

PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'

def enabled():
    return bool(os.environ.get('TOMOH_STORAGE_RELAY_URL'))

def call(action, bucket, object_path, data=None, content_type=None):
    import base64
    body = {'action': action, 'bucket': bucket, 'path': object_path}
    if data is not None:
        body.update(data=base64.b64encode(data).decode(), content_type=content_type)
    req = urllib.request.Request(os.environ['TOMOH_STORAGE_RELAY_URL'],
        data=json.dumps(body).encode(), method='POST',
        headers={'Content-Type':'application/json', 'X-Tomoh-Token':os.environ['TOMOH_STORAGE_TOKEN']})
    with urllib.request.urlopen(req, timeout=30) as res:
        if action == 'download':
            return res.read()
        return json.loads(res.read())

def ensure_template(path):
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        data=call('download','tomoh-templates','master_template.pptx')
        import uuid
        temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temp.write_bytes(data)
        temp.replace(path)

def persist_report(path):
    path=Path(path)
    call('upload','tomoh-reports',path.name,path.read_bytes(),PPTX_MIME)
    return 'supabase://tomoh-reports/'+path.name

def restore_image(path, uploads_dir):
    path=Path(path).resolve()
    path.relative_to(Path(uploads_dir).resolve())
    if not path.name.startswith('upload_') or path.suffix not in ('.png','.jpg','.jpeg'):
        raise ValueError('INVALID_IMAGE_PATH')
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(call('download','tomoh-uploads',path.name))
    return str(path)
