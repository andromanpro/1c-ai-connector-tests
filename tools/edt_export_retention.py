"""Remove reproducible EDT caches while retaining sources and diagnostic evidence."""
from pathlib import Path
import os
import shutil


def cache_targets(export_folder):
    root = Path(export_folder).resolve(strict=True)
    return [root / 'cli-configuration/org.eclipse.osgi',
            root / 'workspace/.metadata/.plugins/com._1c.g5.v8.dt.core/bm-model-manager']


def validate_cache_target(path, allowed_root):
    """Validate both the literal path and every ancestor before recursive removal."""
    root = Path(allowed_root).resolve(strict=True)
    target = Path(os.path.abspath(path))
    if target == root or not target.is_relative_to(root):
        raise ValueError('Cache target must be a descendant of the allowed root')
    relative = target.relative_to(root)
    is_osgi = target.name == 'org.eclipse.osgi' and target.parent.name in ('configuration', 'cli-configuration')
    model_suffix = ('.metadata', '.plugins', 'com._1c.g5.v8.dt.core', 'bm-model-manager')
    is_model = relative.parts[-len(model_suffix):] == model_suffix
    if not (is_osgi or is_model):
        raise ValueError('Unrecognized EDT cache path')
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError('Links are not allowed in a cache deletion path')
    if target.exists() and (not target.is_dir() or target.resolve(strict=True) != target):
        raise ValueError('Cache target does not resolve to the expected directory')
    return target


def remove_cache(path, allowed_root):
    target = validate_cache_target(path, allowed_root)
    if not target.exists():
        return False
    if os.name == 'nt':
        import win32con
        import win32file
        import pywintypes
        locks = [target / '.manager/.fileTableLock']
        if target.name == 'bm-model-manager':
            locks.append(target.parent.parent.parent / '.lock')
        for lock in locks:
            try:
                handle = win32file.CreateFile(str(lock), win32con.GENERIC_READ, 0, None, win32con.OPEN_EXISTING, 0, None)
                handle.Close()
            except pywintypes.error as error:
                if error.winerror not in (2, 3):
                    raise OSError(error.winerror, 'EDT cache lock is in use: ' + str(lock)) from error
    # Junctions nested inside caches are refused as well, before any file is removed.
    stack = [target]
    while stack:
        folder = stack.pop()
        with os.scandir(folder) as stream:
            for entry in stream:
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Link found inside an EDT cache')
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
    shutil.rmtree(target)
    return True


def compact_export(export_folder, keep_workspace=False):
    root = Path(export_folder).resolve(strict=True)
    result = {'policy': 'remove_reproducible_caches', 'keep_workspace': keep_workspace,
              'removed': [], 'errors': [], 'preserved': ['sources', 'exports', 'cli.log', 'workspace/.metadata/.log']}
    if keep_workspace:
        result['policy'] = 'explicit_keep_workspace'
        return result
    for path in cache_targets(root):
        try:
            if remove_cache(path, root):
                result['removed'].append(path.relative_to(root).as_posix())
        except (OSError, ValueError) as error:
            result['errors'].append({'path': path.relative_to(root).as_posix(), 'error': str(error)})
    return result
