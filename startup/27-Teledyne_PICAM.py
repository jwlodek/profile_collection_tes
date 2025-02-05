print(ttime.ctime() + ' >>>> ' + __file__)
import time as ttime  # tea time
from collections import OrderedDict
from types import SimpleNamespace
from datetime import datetime
from ophyd import (PICamDetector, PICamDetectorCam, SingleTrigger,
                   ImagePlugin, StatsPlugin, DetectorBase,
                   AreaDetector, EpicsSignal, EpicsSignalRO, ROIPlugin,
                   TransformPlugin, ProcessPlugin, Device, PICamDetector, PICamDetectorCam)
from ophyd.areadetector.cam import AreaDetectorCam
from ophyd.areadetector.base import ADComponent, EpicsSignalWithRBV
from ophyd.areadetector.filestore_mixins import (FileStoreTIFFIterativeWrite,
                                                 FileStoreHDF5IterativeWrite,
                                                 FileStoreBase, new_short_uid,
                                                 FileStoreIterativeWrite)
from ophyd.areadetector.plugins import (TIFFPlugin_V34 as TIFFPlugin,
                                        HDF5Plugin_V34 as HDF5Plugin)
from ophyd import Component as Cpt, Signal
from ophyd.utils import set_and_wait
from pathlib import PurePath
from bluesky.plan_stubs import stage, unstage, open_run, close_run, trigger_and_read, pause
from nslsii.ad33 import SingleTriggerV33, StatsPluginV33
class PICamDetectorCamV33(PICamDetectorCam):
    wait_for_plugins = Cpt(EpicsSignal, 'WaitForPlugins',
                           string=True, kind='config')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage_sigs['wait_for_plugins'] = 'Yes'

    def ensure_nonblocking(self):
        self.stage_sigs['wait_for_plugins'] = 'Yes'
        for c in self.parent.component_names:
            cpt = getattr(self.parent, c)
            if cpt is self:
               continue
            if hasattr(cpt, 'ensure_nonblocking'):
                cpt.ensure_nonblocking()


class PICamDetectorV33(PICamDetector):
    cam = Cpt(PICamDetectorCamV33, 'cam1:')


class TIFFPluginWithFileStore(TIFFPlugin, FileStoreTIFFIterativeWrite):
    """Add this as a component to detectors that write TIFFs."""
    pass


class HDF5PluginWithFileStoreBase(HDF5Plugin, FileStoreHDF5IterativeWrite):
    ...


class HDF5PluginWithFileStoreBaseRGB(HDF5PluginWithFileStoreBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filestore_spec = "AD_HDF5_RGB"


class HDF5PluginWithFileStorePICam(HDF5PluginWithFileStoreBase):
    """Add this as a component to detectors that write HDF5s."""

    def warmup(self):
        '''
         This is vendored from ophyd (https://github.com/bluesky/ophyd/blob/master/ophyd/areadetector/plugins.py)
         to fix the non-existent "Internal" trigger mode that is hard-coded there:
             In [13]: picam.stage()
             An exception has occurred, use '%tb verbose' to see the full traceback.
             UnprimedPlugin: The plugin hdf5 on the area detector with name picam has not been primed.
             See /home/xf08bm/bluesky-files/log/bluesky/bluesky.log for the full traceback.
             In [14]: picam.hdf5.warmup()
             An exception has occurred, use '%tb verbose' to see the full traceback.
             ValueError: invalid literal for int() with base 0: b'Internal'
             See /home/xf08bm/bluesky-files/log/bluesky/bluesky.log for the full traceback.
        '''

        set_and_wait(self.enable, 1)
        sigs = OrderedDict([(self.parent.cam.array_callbacks, 1),
                            (self.parent.cam.image_mode, 'Single'),
                                (self.parent.cam.trigger_mode, 0),  # updated here "Internal" -> "No Response"
                             # just in case tha acquisition time is set very long...
                            (self.parent.cam.acquire_time, 1),
                            (self.parent.cam.acquire_period, 1),
                            (self.parent.cam.acquire, 1)])

        original_vals = {sig: sig.get() for sig in sigs}

        for sig, val in sigs.items():
            ttime.sleep(0.1)  # abundance of caution
            set_and_wait(sig, val)

        ttime.sleep(2)  # wait for acquisition

        for sig, val in reversed(list(original_vals.items())):
            ttime.sleep(0.1)
            set_and_wait(sig, val)

    def get_frames_per_point(self):
        if not self.parent.is_flying:
            return self.parent.cam.num_images.get()
        else:
            return 1

    def stage(self):
        super().stage()
        set_and_wait(self.enable, 1)
        sigs = OrderedDict([(self.parent.cam.array_callbacks, 1),
                            (self.parent.cam.image_mode, 'Single'),
                            (self.parent.cam.trigger_mode, 0),  # updated here "Internal" -> "No Response"
                            # just in case tha acquisition time is set very long...
                            (self.parent.cam.acquire_time, 1),
                            (self.parent.cam.acquire_period, 1),
                            (self.parent.cam.acquire, 1)])

        original_vals = {sig: sig.get() for sig in sigs}

        for sig, val in sigs.items():
            ttime.sleep(0.1)  # abundance of caution
            set_and_wait(sig, val)

        ttime.sleep(2)  # wait for acquisition

        for sig, val in reversed(list(original_vals.items())):
            ttime.sleep(0.1)
            set_and_wait(sig, val)


class StandardPICam(SingleTriggerV33, PICamDetectorV33):
    image = Cpt(ImagePlugin, 'image1:')
    stats1 = Cpt(StatsPluginV33, 'Stats1:')
    stats2 = Cpt(StatsPluginV33, 'Stats2:')
    stats3 = Cpt(StatsPluginV33, 'Stats3:')
    stats4 = Cpt(StatsPluginV33, 'Stats4:')
    stats5 = Cpt(StatsPluginV33, 'Stats5:')
    trans1 = Cpt(TransformPlugin, 'Trans1:')
    roi1 = Cpt(ROIPlugin, 'ROI1:')
    roi2 = Cpt(ROIPlugin, 'ROI2:')
    roi3 = Cpt(ROIPlugin, 'ROI3:')
    roi4 = Cpt(ROIPlugin, 'ROI4:')
    proc1 = Cpt(ProcessPlugin, 'Proc1:')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._is_flying = False

    @property
    def is_flying(self):
        return self._is_flying

    @is_flying.setter
    def is_flying(self, is_flying):
        self._is_flying = is_flying

    def set_exposure_time(self, exp_time_s):
        exp_time = int(exp_time_s * 1000)
        picam.cam.acquire_time.set(exp_time).wait()
        picam.cam.acquire_period.set(exp_time).wait()

    def read_exposure_time(self):
        return picam.cam.acquire_time.get() / 1000


class StandardPICamWithHDF5(StandardPICam):
    hdf5 = Cpt(HDF5PluginWithFileStorePICam,
               suffix='HDF1:',
               write_path_template="/tmp",
               root='/home/xf08bm/Users/Data/TES/raw/')

# This camera is the default one (with the HDF5 plugin):
 #picam = None
picam = StandardPICamWithHDF5('XF:08BM-ES{Det:PICAM1}', name='picam')


if picam is not None:
    picam.hdf5.write_path_template = "/home/xf08bm/Users/Data/TES/raw/picam/hdf5/%Y/%m/%d/"

     # TODO: do it conditionally when running the code at the beamline only.
    picam.hdf5.create_directory.put(-3)

    picam.cam.ensure_nonblocking()
    for camera in [picam]:
        camera.read_attrs = ['stats1', 'stats2', 'stats3', 'stats4', 'stats5']
        for plugin_type in ['hdf5']:
            if hasattr(camera, plugin_type):
                camera.read_attrs.append(plugin_type)

        for stats_name in ['stats1', 'stats2', 'stats3', 'stats4', 'stats5']:
            stats_plugin = getattr(camera, stats_name)
            stats_plugin.read_attrs = ['total']

        camera.stage_sigs[camera.cam.image_mode] = 'Multiple'

         # 'Sync In 2' is used for fly scans:
         # camera.stage_sigs[camera.cam.trigger_mode] = 'Sync In 2'

         # 'Fixed Rate' is used for step scans:
        camera.stage_sigs[camera.cam.array_counter] = 0
        camera.stats1.total.kind = 'hinted'
        camera.stats2.total.kind = 'hinted'


    for cam in [picam]:
        cam.roi1.kind = "config"
        cam.roi2.kind = "config"
        cam.roi1.size.kind = "config"
        cam.roi1.min_xyz.kind = "config"
        cam.roi2.size.kind = "config"
        cam.roi2.min_xyz.kind = "config"

    # Warm-up the hdf5 plugins:
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

        warmup_hdf5_plugins([picam])