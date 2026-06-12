# app/routes/files_admin.py

from __future__ import annotations

import io

import mimetypes

import shutil

import zipfile

from dataclasses import dataclass

from pathlib import Path

from typing import List



from flask import (

    Blueprint, current_app, render_template, request, redirect, url_for,

    flash, send_file, abort

)

from flask_login import login_required, current_user



files_bp = Blueprint("files_admin", __name__, url_prefix="/admin/files")



# -----------------------

# Guard: sadece 'allah' rolü

# -----------------------

def _is_allah() -> bool:

    return (getattr(current_user, "role", "") or "").lower() == "allah"



def allah_required(view):

    from functools import wraps

    @wraps(view)

    def wrapper(*a, **kw):

        if not current_user.is_authenticated:

            # kendi giriş sayfana yönlendir (auth.login blueprint adını sende neyse ona göre değiştir)

            return redirect(url_for("auth.login", next=request.path))

        if not _is_allah():

            abort(403)

        return view(*a, **kw)

    return wrapper



# -----------------------

# Kök ve güvenli path

# -----------------------

def _project_root() -> Path:
    # Path.cwd().anchor, o an bulunulan diskin kökünü verir (Örn: "C:\" veya "/")
    return Path(Path.cwd().anchor)

def _safe_join(root: Path, *parts: str) -> Path:
    candidate = (root.joinpath(*parts)).resolve()
    
    # Kök dizin tüm diski kapsadığı için startswith kontrolü teknik olarak 
    # sadece o sürücüde kalmayı garanti eder.
    if not str(candidate).startswith(str(root)):
        abort(400, "Path traversal engellendi veya farklı bir sürücüye geçilmeye çalışıldı.")
        
    return candidate


# -----------------------

# Listing yardımcıları

# -----------------------

@dataclass

class Entry:

    name: str

    path_rel: str

    is_dir: bool

    size: int

    mtime: float



def _iter_dir(p: Path, root: Path) -> List[Entry]:

    out: List[Entry] = []

    for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):

        try:

            stat = child.stat()

        except FileNotFoundError:

            continue

        rel = str(child.relative_to(root)).replace("\\", "/")

        out.append(Entry(

            name=child.name,

            path_rel=rel,

            is_dir=child.is_dir(),

            size=0 if child.is_dir() else stat.st_size,

            mtime=stat.st_mtime,

        ))

    return out



# -----------------------

# Metin dosyası algılama

# -----------------------

def _guess_encoding(fp: Path) -> str:

    for enc in ("utf-8", "utf-8-sig", "iso-8859-9", "cp1254"):

        try:

            fp.read_text(encoding=enc)

            return enc

        except Exception:

            continue

    return "utf-8"



def _looks_text(fp: Path) -> bool:

    exts = {".py",".txt",".md",".json",".js",".css",".html",".jinja",".jinja2",".yaml",".yml",".ini",".cfg",".toml",".log"}

    if fp.suffix.lower() in exts:

        return True

    mime, _ = mimetypes.guess_type(fp.name)

    return (mime or "").startswith("text/")



# -----------------------

# Routes

# -----------------------

@files_bp.get("/")

@login_required

@allah_required

def index():

    root = _project_root()

    q = request.args.get("p", "").strip()

    cur = _safe_join(root, q) if q else root

    if not cur.exists():

        abort(404, "Yol bulunamadı.")

    if cur.is_file():

        return redirect(url_for(".view_file", p=str(cur.relative_to(root)).replace("\\", "/")))

    items = _iter_dir(cur, root)

    parent_rel = "" if cur == root else str(cur.parent.relative_to(root)).replace("\\", "/")

    return render_template("admin/files/index.html",

                           root=str(root),

                           cur_rel=str(cur.relative_to(root)).replace("\\", "/") if cur != root else "",

                           parent_rel=parent_rel,

                           items=items,

                           current_user=getattr(current_user, "username", "allah"))



@files_bp.get("/view")

@login_required

@allah_required

def view_file():

    root = _project_root()

    q = request.args.get("p", "")

    fp = _safe_join(root, q)

    if not fp.exists() or not fp.is_file():

        abort(404)

    try:

        size = fp.stat().st_size

    except FileNotFoundError:

        abort(404)

    is_text = _looks_text(fp)

    content = None

    if is_text and size <= 2_500_000:

        content = fp.read_text(encoding=_guess_encoding(fp))

    return render_template("admin/files/edit.html",

                           path_rel=str(fp.relative_to(root)).replace("\\", "/"),

                           filename=fp.name,

                           is_text=is_text,

                           size=size,

                           content=content)



@files_bp.post("/save")

@login_required

@allah_required

def save_file():

    root = _project_root()

    p = request.form.get("p", "")

    data = request.form.get("content", "")

    enc = request.form.get("encoding", "") or "utf-8"

    fp = _safe_join(root, p)

    if not fp.exists() or not fp.is_file():

        abort(404)

    try:

        fp.write_text(data, encoding=enc)

        flash("Dosya kaydedildi.", "success")

    except Exception as e:

        flash(f"Kaydetme hatası: {e}", "danger")

    return redirect(url_for(".view_file", p=p))



def _norm_relpath(s: str) -> str:

    # güvenli ve normalize edilmiş göreli yol: baştaki / \ temizle, .. engelle

    s = (s or "").replace("\\", "/").lstrip("/")

    parts = []

    for p in s.split("/"):

        if p in ("", ".", None):

            continue

        if p == "..":

            # traversal denemesi; görmezden gel

            continue

        parts.append(p)

    return "/".join(parts)



@files_bp.post("/upload")

@login_required

@allah_required

def upload():

    root = _project_root()

    cur = request.form.get("cur", "")

    target = _safe_join(root, cur) if cur else root

    if not target.exists() or not target.is_dir():

        abort(404)



    files = request.files.getlist("files")

    relpaths = request.form.getlist("relpaths")  # klasör yükleme için isteğe bağlı

    overwrite = (request.form.get("overwrite") in ("1", "true", "on", "yes"))



    if not files:

        flash("Dosya seçilmedi.", "warning")

        return redirect(url_for(".index", p=cur))



    # relpaths uzunluğu, files ile aynıysa klasör yapısını koru

    use_paths = len(relpaths) == len(files) and len(files) > 0



    uploaded, skipped, conflicts = 0, 0, []



    for i, f in enumerate(files):

        if not f or not f.filename:

            continue



        if use_paths:

            rel = _norm_relpath(relpaths[i])

            # Eğer tarayıcı boş gönderirse dosya adını kullan

            if not rel:

                rel = _norm_relpath(f.filename)

        else:

            rel = _norm_relpath(f.filename)



        if not rel:

            skipped += 1

            continue



        dest = _safe_join(root, cur, rel)

        dest.parent.mkdir(parents=True, exist_ok=True)



        if dest.exists() and not overwrite:

            conflicts.append(str(dest.relative_to(root)).replace("\\", "/"))

            skipped += 1

            continue



        try:

            # Üstüne yazma da dahil, direkt kaydet

            f.save(str(dest))

            uploaded += 1

        except Exception as e:

            flash(f"'{rel}' yüklenemedi: {e}", "danger")

            skipped += 1



    if conflicts and not overwrite:

        flash(f"{len(conflicts)} öğe zaten mevcut ve atlandı. "

              f"Üzerine yazmak için 'overwrite' ile tekrar yükleyin.", "warning")

        # İstersen ilk birkaç çakışmayı gösterelim

        sample = conflicts[:5]

        flash("Çakışmalar: " + ", ".join(sample) + ("..." if len(conflicts) > 5 else ""), "muted")



    if uploaded:

        flash(f"{uploaded} dosya yüklendi.", "success")

    if skipped and not conflicts:

        flash(f"{skipped} dosya atlandı.", "info")



    return redirect(url_for(".index", p=cur))



@files_bp.post("/new")

@login_required

@allah_required

def new_entry():

    root = _project_root()

    cur = request.form.get("cur", "")

    name = request.form.get("name", "").strip()

    kind = request.form.get("kind", "file")

    if not name:

        flash("İsim gerekli.", "warning")

        return redirect(url_for(".index", p=cur))

    base = _safe_join(root, cur) if cur else root

    dest = _safe_join(root, cur, name)

    try:

        if kind == "dir":

            dest.mkdir(parents=True, exist_ok=False)

        else:

            dest.parent.mkdir(parents=True, exist_ok=True)

            dest.touch(exist_ok=False)

        flash(f"'{name}' oluşturuldu.", "success")

    except FileExistsError:

        flash("Zaten mevcut.", "warning")

    except Exception as e:

        flash(f"Hata: {e}", "danger")

    return redirect(url_for(".index", p=cur))



@files_bp.post("/rename")

@login_required

@allah_required

def rename():

    root = _project_root()

    p = request.form.get("p", "")

    new_name = request.form.get("new_name", "").strip()

    src = _safe_join(root, p)

    if not src.exists():

        abort(404)

    dest = src.parent / new_name

    dest = _safe_join(root, str(dest.relative_to(root)))

    try:

        src.rename(dest)

        flash("Yeniden adlandırıldı.", "success")

        parent_rel = str(dest.parent.relative_to(root)).replace("\\", "/") if dest.parent != root else ""

        return redirect(url_for(".index", p=parent_rel))

    except Exception as e:

        flash(f"Hata: {e}", "danger")

        return redirect(url_for(".index", p=str(src.parent.relative_to(root)).replace("\\", "/")))



@files_bp.post("/delete")

@login_required

@allah_required

def delete():

    root = _project_root()

    items = request.form.getlist("items")

    deleted = 0

    for rel in items:

        target = _safe_join(root, rel)

        try:

            if target.is_dir():

                shutil.rmtree(target)

            else:

                target.unlink()

            deleted += 1

        except Exception:

            continue

    flash(f"{deleted} öğe silindi.", "success")

    cur = request.form.get("cur", "")

    return redirect(url_for(".index", p=cur))



@files_bp.get("/download")

@login_required

@allah_required

def download():

    root = _project_root()

    p = request.args.get("p", "")

    fp = _safe_join(root, p) if p else root

    if not fp.exists():

        abort(404)



    if fp.is_file():

        # tek dosya indir

        return send_file(

            str(fp),

            as_attachment=True,

            download_name=fp.name

        )



    # klasör: zip oluşturup gönder (stream)

    mem = io.BytesIO()

    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:

        for path in fp.rglob("*"):

            arcname = str(path.relative_to(fp)).replace("\\", "/")

            if path.is_dir():

                # Zip dosyasında klasör kaydı zorunlu değil, atla

                continue

            zf.write(path, arcname)

    mem.seek(0)

    zip_name = (fp.name or "project") + ".zip"

    return send_file(mem, as_attachment=True, download_name=zip_name, mimetype="application/zip")

