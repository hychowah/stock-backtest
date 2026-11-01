"""Internal numerical layout, stable identity and attributed admission evidence.

Resource observations are samples, not promises about future availability.
Managed allowances account owned arrays/estimated objects, not total RSS.
Only deliberately selected execution settings enter ``identity``.
"""
from copy import deepcopy
import math
import os
from pathlib import Path
import time


def _positive(value, name, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError('Invalid numerical execution '+name+'.')
    return value


def _linux_resources(result):
    try:
        memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        result['physical_bytes'] = int(memory['MemTotal'].split()[0])*1024
        result['available_bytes'] = int(memory['MemAvailable'].split()[0])*1024
    except (OSError, KeyError, ValueError):
        result['unknown'].append('Linux available memory')
    # Locate this process's actual unified cgroup and every limiting ancestor.
    try:
        group = next(line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines()
                     if line.startswith('0::'))
        mounts = Path('/proc/self/mountinfo').read_text().splitlines()
        mount = next(line.split() for line in mounts if ' - cgroup2 ' in line)
        root, location = mount[3], Path(mount[4])
        relative = Path(group).relative_to(root)
        current = location/relative
        constraints = []
        while current == location or location in current.parents:
            row = dict(path=str(current))
            for name in ('cpu.max', 'memory.max', 'memory.high', 'memory.current', 'pids.max',
                         'cpuset.cpus.effective'):
                try: row[name] = (current/name).read_text().strip()
                except OSError: row[name] = None
            constraints.append(row)
            if current == location: break
            current = current.parent
        result['cgroups'] = constraints
        quotas, headrooms = [], []
        for row in constraints:
            if row['cpu.max']:
                quota, period = row['cpu.max'].split()
                if quota != 'max': quotas.append(int(quota)/int(period))
            if row['memory.max'] not in (None, 'max') and row['memory.current']:
                headrooms.append(max(0, int(row['memory.max'])-int(row['memory.current'])))
        result['cpu_quota_lanes'] = min(quotas) if quotas else None
        result['container_headroom_bytes'] = min(headrooms) if headrooms else None
    except (OSError, StopIteration, ValueError, IndexError):
        result['unknown'].append('Applicable cgroup hierarchy')
    result['unknown'].append('Non-cgroup host reservations and future memory availability')


def _windows_resources(result):
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.GetProcessAffinityMask.argtypes = [w.HANDLE, c.POINTER(c.c_size_t), c.POINTER(c.c_size_t)]
    process, system = c.c_size_t(), c.c_size_t()
    if kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), c.byref(process), c.byref(system)):
        result['affinity_cpus'] = process.value.bit_count()
        result['affinity_mask'] = process.value
    else: result['unknown'].append('Native process affinity')
    class Memory(c.Structure):
        _fields_ = [('length', w.DWORD), ('load', w.DWORD)]+[(name, c.c_ulonglong) for name in
            ('total_physical', 'available_physical', 'total_commit', 'available_commit',
             'total_virtual', 'available_virtual', 'extended')]
    memory = Memory(); memory.length = c.sizeof(memory)
    if kernel.GlobalMemoryStatusEx(c.byref(memory)):
        result.update(physical_bytes=memory.total_physical, available_bytes=memory.available_physical,
                      commit_headroom_bytes=memory.available_commit)
    else: result['unknown'].append('Native physical memory and commit headroom')
    class Basic(c.Structure):
        _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
            ('min_working', c.c_size_t), ('max_working', c.c_size_t), ('processes', w.DWORD),
            ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
    class Extended(c.Structure):
        _fields_ = [('basic', Basic), ('io', c.c_uint64*6), ('process_memory', c.c_size_t),
            ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]
    class Rate(c.Structure):
        _fields_ = [('flags', w.DWORD), ('rate', w.DWORD)]
    kernel.QueryInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]
    extended, rate = Extended(), Rate()
    if kernel.QueryInformationJobObject(None, 9, c.byref(extended), c.sizeof(extended), None):
        result['current_job'] = dict(flags=extended.basic.flags,
            process_limit=extended.basic.processes if extended.basic.flags & 8 else None,
            process_memory_bytes=extended.process_memory if extended.basic.flags & 0x100 else None,
            job_memory_bytes=extended.job_memory if extended.basic.flags & 0x200 else None)
        if kernel.QueryInformationJobObject(None, 15, c.byref(rate), c.sizeof(rate), None):
            result['current_job']['cpu_rate_flags'] = rate.flags
            result['current_job']['cpu_rate'] = rate.rate if rate.flags & 1 else None
            if rate.flags & 5 == 5:
                result['cpu_quota_lanes'] = result['affinity_cpus']*rate.rate/10000
    else: result['current_job'] = None
    result['unknown'].extend(('Nested job constraints beyond current job',
                              'Processor groups beyond the current affinity mask',
                              'Future memory and commit availability'))


def observe_resources():
    result = dict(observed_at=time.time(), logical_cpus=os.cpu_count(), affinity_cpus=None,
        cpu_quota_lanes=None, physical_bytes=None, available_bytes=None,
        commit_headroom_bytes=None, container_headroom_bytes=None, unknown=[])
    if hasattr(os, 'sched_getaffinity'):
        try: result['affinity_cpus'] = len(os.sched_getaffinity(0))
        except OSError: result['unknown'].append('Process affinity')
    if os.name == 'nt': _windows_resources(result)
    elif Path('/proc').is_dir(): _linux_resources(result)
    else: result['unknown'].append('Platform resource restrictions')
    return result


def effective_lanes(observations):
    counts = [observations.get(name) for name in ('affinity_cpus', 'logical_cpus', 'cpu_quota_lanes')]
    counts = [value for value in counts if type(value) in (int, float) and value > 0]
    return max(1, math.floor(min(counts))) if counts else 1


def initial_threads(observations=None):
    # Four is an initial sequential comparison point, not a machine ceiling.
    return min(4, effective_lanes(observations or observe_resources()))


def numba_threads(requested, maximum):
    requested = initial_threads() if requested is None else _positive(requested, 'threads')
    if requested > maximum:
        raise ValueError('Selected numerical threads exceed the initialized Numba team. Start a fresh runtime.')
    return requested


class ExecutionPolicy:
    def __init__(self, settings=None, *, observations=None, coordinator=True):
        settings = deepcopy(settings or {})
        allowed = {'backend', 'workers', 'threads_per_worker', 'lane_budget', 'workspace_bytes',
            'matrix_cache_bytes', 'pending_slots', 'artifact_bytes', 'artifact_total_bytes',
            'piece_bytes', 'record_bytes', 'private_memory_budget_bytes', 'chunk_rows',
            'start_seconds', 'close_seconds'}
        if set(settings)-allowed: raise ValueError('Unknown internal numerical execution setting.')
        self.backend=settings.get('backend','numba')
        if self.backend not in ('numba','numba_compiled','rust'):
            raise ValueError('Unknown trusted numerical comparison configuration.')
        self.observations = deepcopy(observations if observations is not None else observe_resources())
        self.workers = _positive(settings.get('workers', 1), 'workers')
        lanes = _positive(settings.get('lane_budget', effective_lanes(self.observations)), 'lane budget')
        threads = _positive(settings.get('threads_per_worker', min(4, lanes)), 'threads')
        if self.workers*threads > lanes:
            raise ValueError('Numerical workers times threads exceed the selected numerical-lane budget.')
        providers = self.workers+int(coordinator)
        # Retain existing per-book capacity. Resolve and expose the aggregate
        # before division; cold-cost admission separately gates duplication.
        workspace = _positive(settings.get('workspace_bytes', providers*64*1024**2), 'workspace bytes')
        cache = _positive(settings.get('matrix_cache_bytes', providers*16*1024**2), 'cache bytes', zero=True)
        if workspace < providers:
            raise ValueError('Total numerical workspace cannot cover every live provider.')
        slots = _positive(settings.get('pending_slots', self.workers), 'pending slots')
        if slots < self.workers: raise ValueError('Pending slots must cover the selected workers.')
        artifact = _positive(settings.get('artifact_bytes', 64*1024**2), 'artifact bytes')
        total = _positive(settings.get('artifact_total_bytes', artifact*slots), 'total artifact bytes')
        if slots*artifact > total:
            raise ValueError('Task reservations exceed the total provisional artifact allowance.')
        piece = _positive(settings.get('piece_bytes', 1024*1024), 'piece bytes')
        record = _positive(settings.get('record_bytes', 8*1024*1024), 'record bytes')
        if piece > 1024*1024 or record > 8*1024*1024 or piece > artifact:
            raise ValueError('Invalid numerical evidence protocol limits.')
        self.start_seconds = settings.get('start_seconds', 120.)
        self.close_seconds = settings.get('close_seconds', 30.)
        for value in (self.start_seconds, self.close_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid numerical lifecycle timeout.')
        self.private_memory_budget_bytes = settings.get('private_memory_budget_bytes')
        if self.private_memory_budget_bytes is not None:
            _positive(self.private_memory_budget_bytes, 'private memory admission bytes')
        self._identity = dict(version=1, workers=self.workers, threads_per_worker=threads,
            numerical_lane_budget=lanes, live_providers=providers,
            workspace_total_bytes=workspace, matrix_cache_total_bytes=cache,
            provider_limits=dict(threads=threads, request_plan=True, candidate_assembly=('source' if self.backend=='numba' else 'compiled'),
                workspace_bytes=workspace//providers, matrix_cache_bytes=cache//providers,
                chunk_rows=_positive(settings.get('chunk_rows', 1024), 'chunk rows')),
            pending_slots=slots, artifact_total_bytes=total,
            artifact_limits=dict(max_bytes=artifact, piece_bytes=piece, record_bytes=record))
        if self.backend=='rust':self._identity['provider_limits']['backend']='rust'
        self.provenance = dict(
            layout='Explicit internal experiment' if 'workers' in settings else
                   'One worker until CB-19F qualifies duplication and scaling',
            threads='Explicit internal experiment' if 'threads_per_worker' in settings else
                    'Initial four-thread comparison, bounded by effective observed CPU entitlement',
            lanes='Explicit internal experiment' if 'lane_budget' in settings else
                  'Minimum observed affinity, visible CPUs and CPU quota; unknowns remain recorded',
            managed='Explicit totals, or existing 64 MiB workspace and 16 MiB cache compatibility allowances '
                    'per live provider; aggregate recorded, divided, and duplication cold-cost gated',
            artifacts='Finite encoded evidence reservations; default 64 MiB per task slot',
            lifecycle='Configurable cold initialization and cleanup response allowances; no calculation watchdog',
            memory='Cold private-memory sample gates duplication; admission estimate only, never an RSS limit')

    @property
    def identity(self): return deepcopy(self._identity)

    @property
    def provider_limits(self): return deepcopy(self._identity['provider_limits'])

    @property
    def artifact_limits(self): return deepcopy(self._identity['artifact_limits'])

    def execution_identity(self, compiler):
        """Expected stable worker contract; no process or JIT is needed."""
        return dict(**self.identity, backend='rust' if self.backend=='rust' else 'numba', compiler=compiler['signature'])

    def admit_cold_worker(self, measurements):
        """Check incremental duplication before starting remaining workers.

        The coordinator is already resident. Available-memory observations
        exclude it. A declared experiment budget covers all worker cold costs.
        Neither observation can bound later native/Python allocations.
        """
        cost = measurements.get('sampled_private_bytes')
        if self.workers == 1: return dict(cold_private_bytes=cost, duplication_bytes=0)
        if type(cost) is not int or cost <= 0:
            raise ValueError('Parallel worker admission requires a measured cold private-memory cost.')
        observation = observe_resources()
        available = [observation.get(name) for name in
            ('available_bytes', 'commit_headroom_bytes', 'container_headroom_bytes')]
        available = [value for value in available if type(value) is int]
        if not available and self.private_memory_budget_bytes is None:
            raise ValueError('Parallel worker admission lacks a memory observation or internal allowance.')
        additional = cost*(self.workers-1)
        if available and additional > min(available):
            raise ValueError('Cold worker duplication exceeds observed available memory or commit headroom.')
        if (self.private_memory_budget_bytes is not None
                and cost*self.workers > self.private_memory_budget_bytes):
            raise ValueError('Cold workers exceed the declared private-memory admission allowance.')
        return dict(cold_private_bytes=cost, duplication_bytes=additional,
                    observations=observation, private_memory_budget_bytes=self.private_memory_budget_bytes)

    def diagnostics(self):
        return dict(execution=self.identity, observations=deepcopy(self.observations),
            provenance=deepcopy(self.provenance), start_seconds=self.start_seconds,
            close_seconds=self.close_seconds, private_memory_budget_bytes=self.private_memory_budget_bytes)
