from ophyd.signal import EpicsSignalBase
EpicsSignalBase.set_defaults(timeout=10, connection_timeout=10)

from nslsii import configure_base
from IPython import get_ipython

import sys
import os

# Addressed following https://www.nsls2.bnl.gov/docs/how-to/hot-fix-envs.html.
# sys.path.insert(0, os.path.expanduser('~/src/bloptools'))
from bloptools import gp


configure_base(get_ipython().user_ns,
               "tes",
               publish_documents_with_kafka=True)

import logging

from pathlib import Path
import appdirs


try:
    from bluesky.utils import PersistentDict
except ImportError:
    import msgpack
    import msgpack_numpy
    import zict

    class PersistentDict(zict.Func):
        """
        A MutableMapping which syncs it contents to disk.
        The contents are stored as msgpack-serialized files, with one file per item
        in the mapping.
        Note that when an item is *mutated* it is not immediately synced:
        >>> d['sample'] = {"color": "red"}  # immediately synced
        >>> d['sample']['shape'] = 'bar'  # not immediately synced
        but that the full contents are synced to disk when the PersistentDict
        instance is garbage collected.
        """
        def __init__(self, directory):
            self._directory = directory
            self._file = zict.File(directory)
            self._cache = {}
            super().__init__(self._dump, self._load, self._file)
            self.reload()

            # Similar to flush() or _do_update(), but without reference to self
            # to avoid circular reference preventing collection.
            # NOTE: This still doesn't guarantee call on delete or gc.collect()!
            #       Explicitly call flush() if immediate write to disk required.
            def finalize(zfile, cache, dump):
                zfile.update((k, dump(v)) for k, v in cache.items())

            import weakref
            self._finalizer = weakref.finalize(
                self, finalize, self._file, self._cache, PersistentDict._dump)

        @property
        def directory(self):
            return self._directory

        def __setitem__(self, key, value):
            self._cache[key] = value
            super().__setitem__(key, value)

        def __getitem__(self, key):
            return self._cache[key]

        def __delitem__(self, key):
            del self._cache[key]
            super().__delitem__(key)

        def __repr__(self):
            return f"<{self.__class__.__name__} {dict(self)!r}>"

        @staticmethod
        def _dump(obj):
            "Encode as msgpack using numpy-aware encoder."
            # See https://github.com/msgpack/msgpack-python#string-and-binary-type
            # for more on use_bin_type.
            return msgpack.packb(
                obj,
                default=msgpack_numpy.encode,
                use_bin_type=True)

        @staticmethod
        def _load(file):
            return msgpack.unpackb(
                file,
                object_hook=msgpack_numpy.decode,
                raw=False)

        def flush(self):
            """Force a write of the current state to disk"""
            for k, v in self.items():
                super().__setitem__(k, v)

        def reload(self):
            """Force a reload from disk, overwriting current cache"""
            self._cache = dict(super().items())


# runengine_metadata_dir = appdirs.user_data_dir(appname="bluesky") / Path("runengine-metadata")
# runengine_metadata_dir = Path('/nsls2/xf08bm/shared/config/runengine-metadata')
runengine_metadata_dir = Path("/nsls2/data/tes/shared/config/runengine-metadata")

# PersistentDict will create the directory if it does not exist
RE.md = PersistentDict(runengine_metadata_dir)


# Optional: set any metadata that rarely changes.
RE.md["beamline_id"] = "TES"


def warmup_hdf5_plugins(detectors):
    """
    Warm-up the hdf5 plugins.

    This is necessary for when the corresponding IOC restarts we have to trigger one image
    for the hdf5 plugin to work correctly, else we get file writing errors.

    Parameter:
    ----------
    detectors: list
    """
    for det in detectors:
        _array_size = det.hdf5.array_size.get()
        if 0 in [_array_size.height, _array_size.width] and hasattr(det, "hdf5"):
            print(f"\n  Warming up HDF5 plugin for {det.name} as the array_size={_array_size}...")
            det.hdf5.warmup()
            print(f"  Warming up HDF5 plugin for {det.name} is done. array_size={det.hdf5.array_size.get()}\n")
        else:
            print(f"\n  Warming up of the HDF5 plugin is not needed for {det.name} as the array_size={_array_size}.")
