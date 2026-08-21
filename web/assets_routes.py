from __future__ import annotations

import os

import flask

from services.data_store import ASSETS_DIR, PHOTO_DIR, RAW_DIR


_IMG_EXTS = ('png', 'jpg', 'jpeg')
_RAW_IMAGE_ALLOWLIST = {'등급 개요.png', 'lv 개요.png'}


def register_asset_routes(server) -> None:
    @server.route('/photo/<rid>')
    def serve_photo(rid):
        rid8 = rid.zfill(8) if rid.isdigit() else None
        if rid8 is None:
            flask.abort(404)
        rid_plain = str(int(rid8))
        candidates = {rid8.lower(), rid_plain.lower()}
        for base_dir in (PHOTO_DIR, os.path.join(ASSETS_DIR, 'photos'), RAW_DIR):
            if not os.path.isdir(base_dir):
                continue
            for fname in os.listdir(base_dir):
                stem, dot, fext = fname.rpartition('.')
                if dot and stem.lower() in candidates and fext.lower() in _IMG_EXTS:
                    return flask.send_file(os.path.join(base_dir, fname))
        flask.abort(404)

    @server.route('/raw-image/<path:filename>')
    def serve_raw_image(filename):
        if filename not in _RAW_IMAGE_ALLOWLIST:
            flask.abort(404)
        path = os.path.join(RAW_DIR, filename)
        if not os.path.isfile(path):
            flask.abort(404)
        return flask.send_file(path)
