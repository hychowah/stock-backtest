"""Durable authored variables, separate from financial caches and saved results.

Content revisions come only from definitions. Entry versions protect mutable
names, favourites and current-revision pointers from stale writers. Every public
operation closes its connection before returning. Imports and construction do
no I/O. There is no server worker, financial ownership or automatic eviction.

SQLite commit publishes a mutation. Deleted entries remain as hidden metadata
receipts; every immutable authored revision is retained for exact references.
An absent, unreadable or unsupported store is never rebuilt from financial data.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import uuid

from backtest.paths import ROOT
from backtest.runtime import backtest_control
from backtest.variables import definitions, measures

DATABASE = ROOT / 'data' / 'variable-library.sqlite'
SCHEMA_VERSION = 1
APPLICATION_ID = 0x43564C31
WAIT_SECONDS = 2
CAPTURE_BYTES = 3 * 1024 * 1024
_MAX_VERSION = 2 ** 63 - 1
_ID = re.compile(r'var:[0-9a-f]{32}\Z')
_REVISION = re.compile(r'sha256:[0-9a-f]{64}\Z')
_SCHEMA = (
    '''CREATE TABLE entries (
        variable_id TEXT PRIMARY KEY, name TEXT NOT NULL,
        favourite INTEGER NOT NULL CHECK(favourite IN (0,1)),
        revision TEXT NOT NULL, version INTEGER NOT NULL CHECK(version > 0),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        deleted INTEGER NOT NULL CHECK(deleted IN (0,1)))''',
    '''CREATE TABLE revisions (
        variable_id TEXT NOT NULL, revision TEXT NOT NULL,
        definition TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(variable_id, revision))''',
)
_COLUMNS = {
    'entries': ('variable_id', 'name', 'favourite', 'revision', 'version',
                'created_at', 'updated_at', 'deleted'),
    'revisions': ('variable_id', 'revision', 'definition', 'created_at'),
}


class Missing(ValueError):
    """An active entry is absent; deleted revisions can still resolve exactly."""


class Conflict(ValueError):
    """The expected mutable entry version no longer matches published state."""


class Unavailable(ValueError):
    """Storage cannot complete now. No successful publication is reported."""


class InvalidStore(ValueError):
    """Unrecognized or damaged durable data was preserved, never replaced."""


def _name(value):
    if type(value) is not str or not 1 <= len(value.strip()) <= 120:
        raise ValueError('Use a variable name with 1–120 characters.')
    return value.strip()


def _favourite(value):
    if type(value) is not bool:
        raise ValueError('Favourite status must be true or false.')
    return value


def _identifier(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError('Invalid variable library ID.')


def _version(value):
    if type(value) is not int or not 1 <= value < _MAX_VERSION:
        raise ValueError('A positive bounded entry version is required.')


def _now():
    return datetime.now(timezone.utc).isoformat()


def _storage_error(error):
    # Error text can contain local paths. Only safe categories leave this owner.
    code = getattr(error, 'sqlite_errorcode', 0) & 0xff
    if code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_SCHEMA,
                sqlite3.SQLITE_ERROR, sqlite3.SQLITE_CONSTRAINT):
        return InvalidStore('The variable library is damaged or unsupported. Its data was kept.')
    return Unavailable('The variable library is unavailable. Retry the operation.')


def _capture_error(code, path, message):
    raise definitions.FormulaError(code, path, message)


def _capture_shape(value, fields, path):
    if type(value) is not dict or set(value) != set(fields):
        _capture_error('INVALID_SHAPE', path, 'Fields do not match the variable capture shape.')


def _capture_bound(value):
    if type(value) is not int or not 1 <= value <= CAPTURE_BYTES:
        _capture_error('CAPTURE_LIMIT', '/limits/bytes', 'Capture byte limit must lower the fixed ceiling.')
    return value


def _capture_encode(value, bound, checkpoint):
    """Bound complete canonical ASCII content while encoding; never truncate."""
    parts, size = [], 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    for part in encoder.iterencode(value):
        checkpoint()
        size += len(part)
        if size > bound:
            _capture_error('CAPTURE_LIMIT', '', 'Complete variable capture exceeds its byte bound.')
        parts.append(part)
    checkpoint()
    return ''.join(parts)


@dataclass(frozen=True)
class VariableCapture:
    """Detached program and presentation bytes, restored without a library.

    A library name describes its capture-time metadata, including deleted
    archives. It does not name an original revision authoring event. Favourite
    state is not calculation presentation. Use require_capture before consuming
    restored bytes; the program accessor performs that check automatically.
    """
    document: str

    def to_dict(self):
        return json.loads(self.document)

    def to_json(self):
        return self.document

    @property
    def program(self):
        checked = require_capture(self)
        return definitions.FormulaProgram(definitions.canonical(checked['program']))


def require_capture(capture, *, checkpoint=backtest_control.checkpoint):
    """Check complete detached capture bytes, including the embedded program.

    The program's existing restore boundary owns all language, hash, unit and
    graph checks. Provenance describes the captured source; it grants no claim
    about current library state. No storage or financial operation occurs here.
    """
    checkpoint()
    if type(capture) is not VariableCapture or type(capture.document) is not str:
        _capture_error('INVALID_SHAPE', '', 'An immutable variable capture is required.')
    if len(capture.document) > CAPTURE_BYTES:
        _capture_error('CAPTURE_LIMIT', '', 'Serialized variable capture exceeds its byte bound.')
    try:
        value = capture.to_dict()
    except (TypeError, ValueError, RecursionError):
        _capture_error('INVALID_SHAPE', '', 'Variable capture is malformed.')
    _capture_shape(value, ('format', 'version', 'program', 'presentation', 'limits'), '')
    if value['format'] != 'variable-capture' or type(value['version']) is not int or value['version'] != 1:
        _capture_error('UNKNOWN_VERSION', '', 'Unsupported variable capture version.')
    _capture_shape(value['limits'], ('bytes',), '/limits')
    bound = _capture_bound(value['limits']['bytes'])
    if len(capture.document) > bound:
        _capture_error('CAPTURE_LIMIT', '', 'Serialized variable capture exceeds its recorded byte bound.')
    checkpoint()
    try:
        program = definitions.FormulaProgram(definitions.canonical(value['program']))
    except (TypeError, ValueError, RecursionError):
        _capture_error('INVALID_SHAPE', '/program', 'Captured formula program is malformed.')
    checked = definitions.require_program(program)
    checkpoint()
    entries = checked['bundle']['definitions']
    presentation = value['presentation']
    if type(presentation) is not list or len(presentation) != len(entries):
        _capture_error('INVALID_SHAPE', '/presentation', 'Every captured definition needs one presentation entry.')
    for index, (item, entry) in enumerate(zip(presentation, entries)):
        checkpoint()
        path = '/presentation/' + str(index)
        _capture_shape(item, ('variable_id', 'revision', 'name', 'provenance'), path)
        if any(item[key] != entry[key] for key in ('variable_id', 'revision')):
            _capture_error('INVALID_SHAPE', path, 'Presentation order must match exact program identities.')
        provenance = item['provenance']
        if type(provenance) is not dict:
            _capture_error('INVALID_SHAPE', path + '/provenance', 'Captured provenance is required.')
        if provenance.get('source') == 'submitted':
            _capture_shape(provenance, ('source',), path + '/provenance')
        elif provenance.get('source') == 'library':
            _capture_shape(provenance, ('source', 'version', 'deleted'), path + '/provenance')
            if (not _ID.fullmatch(item['variable_id']) or type(provenance['version']) is not int or
                    not 1 <= provenance['version'] <= _MAX_VERSION or type(provenance['deleted']) is not bool):
                _capture_error('INVALID_SHAPE', path + '/provenance', 'Library provenance is invalid.')
        else:
            _capture_error('INVALID_SHAPE', path + '/provenance', 'Unknown captured provenance.')
        # A submission-local fallback preserves the complete language ID, whose
        # bound is 128 characters. User-supplied names retain the 120 limit.
        if not (provenance['source'] == 'submitted' and item['name'] == item['variable_id']):
            try:
                if _name(item['name']) != item['name']:
                    raise ValueError()
            except (TypeError, ValueError):
                _capture_error('INVALID_SHAPE', path + '/name', 'Captured names must contain 1–120 trimmed characters.')
    document = _capture_encode(value, bound, checkpoint)
    if document != capture.document:
        _capture_error('INVALID_SHAPE', '', 'Variable capture must use its canonical checked representation.')
    checkpoint()
    return value


def _capture_limits(limits):
    if limits is not None and type(limits) is not dict:
        _capture_error('INVALID_SHAPE', '/limits', 'Capture limits must be an object.')
    formula_limits = dict(limits or {})
    bound = _capture_bound(formula_limits.pop('capture_bytes', CAPTURE_BYTES))
    return formula_limits, bound


def _finish_capture(program, archived, metadata, labels, bound, checkpoint):
    """One envelope policy for snapshot-backed and submission-only captures."""
    checked = definitions.require_program(program)
    entries = checked['bundle']['definitions']
    local = {(entry['variable_id'], entry['revision']) for entry in entries} - archived
    labels = [] if labels is None else labels
    if type(labels) is not list or len(labels) > len(local):
        _capture_error('INVALID_SHAPE', '/labels', 'Labels must name unique submitted definitions only.')
    names = {}
    for index, label in enumerate(labels):
        checkpoint()
        path = '/labels/' + str(index)
        _capture_shape(label, ('variable_id', 'revision', 'name'), path)
        if type(label['variable_id']) is not str or type(label['revision']) is not str:
            _capture_error('INVALID_SHAPE', path, 'A submitted exact identity is required.')
        identity = label['variable_id'], label['revision']
        if identity not in local or identity in names:
            _capture_error('INVALID_SHAPE', path, 'Labels must name unique submitted definitions only.')
        try:
            names[identity] = _name(label['name'])
        except (TypeError, ValueError):
            _capture_error('INVALID_SHAPE', path + '/name', 'Use a submitted name with 1–120 characters.')
    presentation = []
    for entry in entries:
        checkpoint()
        identity = entry['variable_id'], entry['revision']
        if identity in archived:
            record = metadata(identity)
            name = record['name']
            provenance = dict(source='library', version=record['version'], deleted=record['deleted'])
        else:
            name = names.get(identity, identity[0])
            provenance = dict(source='submitted')
        presentation.append(dict(variable_id=identity[0], revision=identity[1],
                                 name=name, provenance=provenance))
    value = dict(format='variable-capture', version=1, program=checked,
                 presentation=presentation, limits=dict(bytes=bound))
    captured = VariableCapture(_capture_encode(value, bound, checkpoint))
    require_capture(captured, checkpoint=checkpoint)
    checkpoint()
    return captured


def capture_submitted(roots, *, submitted, labels=None, limits=None,
                      checkpoint=backtest_control.checkpoint):
    """Capture an unsaved complete program without opening or creating storage.

    Only submitted authored definitions can resolve. Missing dependencies fail
    through the existing resolver. Labels, limits, provenance and checked restore
    are identical to Store.capture's submitted content. No library is consulted.
    """
    formula_limits, bound = _capture_limits(limits)
    program = definitions.resolve(roots, lambda *identity: None, submitted=submitted,
                                  limits=formula_limits, checkpoint=checkpoint)
    return _finish_capture(program, set(), None, labels, bound, checkpoint)


class Store:
    """Short transactional operations over one durable variable library.

    Mutations require the entry version returned by get/list/create/edit. Stale
    writes conflict even if their submitted formula is numerically equivalent.
    A successful no-op keeps its version and timestamps. A formula edit changes
    the content revision only when normalized content differs. Raw authored
    spelling is retained in the first immutable row, including short exponents.
    """
    def __init__(self, path=DATABASE):
        self.path = Path(path)

    @staticmethod
    def _schema(db, initialize):
        application = db.execute('PRAGMA application_id').fetchone()[0]
        version = db.execute('PRAGMA user_version').fetchone()[0]
        objects = db.execute("SELECT name,type,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        if not objects and application == 0 and version == 0 and initialize:
            for command in _SCHEMA:
                db.execute(command)
            db.execute(f'PRAGMA application_id={APPLICATION_ID}')
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        elif not objects and application == 0 and version == 0:
            raise Missing('Variable library has no published entries.')
        elif (application != APPLICATION_ID or version != SCHEMA_VERSION or
              {(row['name'], row['type']) for row in objects} != {(name, 'table') for name in _COLUMNS}):
            raise InvalidStore('Unsupported variable library schema. Its data was kept.')
        else:
            expected = {' '.join(command.split()).casefold() for command in _SCHEMA}
            if {' '.join(row['sql'].split()).casefold() for row in objects} != expected:
                raise InvalidStore('Unsupported variable library schema. Its data was kept.')
        for table, columns in _COLUMNS.items():
            actual = tuple(row['name'] for row in db.execute('PRAGMA table_info(' + table + ')'))
            if actual != columns:
                raise InvalidStore('Unsupported variable library schema. Its data was kept.')

    @contextmanager
    def _transaction(self, *, write=False, checkpoint=backtest_control.checkpoint):
        """One snapshot or serialized mutation; commit alone publishes writes.

        Bounded SQLite waits handle cross-instance contention. Cancellation is
        checked before opening, after ownership, and immediately before commit.
        Exceptions roll back and close the connection, including BaseException.
        """
        checkpoint()
        db = None
        try:
            if write:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            elif not self.path.exists():
                raise Missing('Variable library not found.')
            uri = self.path.resolve().as_uri() + ('?mode=rwc' if write else '?mode=rw')
            db = sqlite3.connect(uri, uri=True, timeout=WAIT_SECONDS, isolation_level=None)
            db.row_factory = sqlite3.Row
            if write:
                db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            self._schema(db, write)
            checkpoint()
            yield db
            checkpoint()
            if write:
                db.commit()
        except (sqlite3.DatabaseError, OSError) as error:
            raise _storage_error(error) from None
        finally:
            if db is not None:
                try:
                    if db.in_transaction:
                        db.rollback()
                finally:
                    db.close()

    @staticmethod
    def _metadata(row):
        if (type(row['version']) is not int or not 1 <= row['version'] <= _MAX_VERSION or
                row['favourite'] not in (0, 1) or row['deleted'] not in (0, 1)):
            raise InvalidStore('Invalid variable metadata. Its data was kept.')
        try:
            _identifier(row['variable_id'])
            if _name(row['name']) != row['name']:
                raise ValueError()
            if type(row['revision']) is not str or not _REVISION.fullmatch(row['revision']):
                raise ValueError()
        except (TypeError, ValueError):
            raise InvalidStore('Invalid variable metadata. Its data was kept.') from None
        for field in ('created_at', 'updated_at'):
            if type(row[field]) is not str:
                raise InvalidStore('Invalid variable metadata. Its data was kept.')
        return dict(variable_id=row['variable_id'], name=row['name'], favourite=bool(row['favourite']),
                    revision=row['revision'], version=row['version'], created_at=row['created_at'],
                    updated_at=row['updated_at'], deleted=bool(row['deleted']))

    @classmethod
    def _active(cls, db, variable_id, expected_version=None):
        row = db.execute('SELECT * FROM entries WHERE variable_id=? AND deleted=0', (variable_id,)).fetchone()
        if row is None:
            raise Missing('Variable library entry not found.')
        record = cls._metadata(row)
        if expected_version is not None and record['version'] != expected_version:
            raise Conflict('This variable changed. Read the current entry before editing it.')
        return record

    @staticmethod
    def _lookup(db, variable_id, revision):
        # Bound decoding before reading the full authored document from SQLite.
        row = db.execute('SELECT substr(definition,1,?),length(definition) FROM revisions '
                         'WHERE variable_id=? AND revision=?',
                         (definitions.CEILINGS['bytes'] + 1, variable_id, revision)).fetchone()
        if row is None:
            return None
        if type(row[0]) is not str or row[1] > definitions.CEILINGS['bytes']:
            raise InvalidStore('Invalid variable revision. Its data was kept.')
        try:
            definition = json.loads(row[0])
        except (TypeError, ValueError, RecursionError):
            raise InvalidStore('Invalid variable revision. Its data was kept.') from None
        if definition is None:
            # None means an absent row to the resolver, never stored content.
            raise InvalidStore('Invalid variable revision. Its data was kept.')
        return definition

    @classmethod
    def _resolve_exact(cls, db, variable_id, revision):
        """Resolve an exact reference from submitted content, a checked archive row, or a matching immutable built-in definition. Built-in resolution never imports library entries or substitutes another revision."""
        definition = cls._lookup(db, variable_id, revision)
        if definition is not None:
            return definition
        builtin = measures.exact(variable_id, revision)
        return builtin['definition'] if builtin else None

    @classmethod
    def _admit(cls, db, variable_id, definition, checkpoint):
        # The definition owner alone computes identity, normalizes and resolves.
        revision = definitions.revision(definition)
        authored = definitions.canonical(definition)
        if len(authored) > definitions.CEILINGS['bytes']:
            raise definitions.FormulaError('DEFINITION_LIMIT', '', 'Formula definition exceeds its byte bound.')
        definition = json.loads(authored)
        root = dict(variable_id=variable_id, revision=revision)
        definitions.resolve([root], lambda *identity: cls._resolve_exact(db, *identity),
                            submitted=[dict(root, definition=definition)], checkpoint=checkpoint)
        if cls._lookup(db, variable_id, revision) is not None:
            # A reused immutable row must also remain valid. Never conceal a
            # damaged archived row by keeping only its matching primary key.
            definitions.resolve([root], lambda *identity: cls._resolve_exact(db, *identity),
                                checkpoint=checkpoint)
        return revision, authored

    def list(self):
        """Return active metadata only. An absent store is an empty library."""
        try:
            with self._transaction() as db:
                return [self._metadata(row) for row in db.execute(
                    'SELECT * FROM entries WHERE deleted=0 ORDER BY created_at,variable_id')]
        except Missing:
            return []

    def get(self, variable_id):
        """Read one active entry; revision content is obtained by exact resolve."""
        _identifier(variable_id)
        with self._transaction() as db:
            return self._active(db, variable_id)

    def create(self, name, definition, *, favourite=False, checkpoint=backtest_control.checkpoint):
        """Atomically publish an entry and its checked immutable authored revision."""
        name, favourite = _name(name), _favourite(favourite)
        variable_id, timestamp = 'var:' + uuid.uuid4().hex, _now()
        with self._transaction(write=True, checkpoint=checkpoint) as db:
            revision, authored = self._admit(db, variable_id, definition, checkpoint)
            db.execute('INSERT INTO revisions VALUES(?,?,?,?)', (variable_id, revision, authored, timestamp))
            db.execute('INSERT INTO entries VALUES(?,?,?,?,?,?,?,0)',
                       (variable_id, name, int(favourite), revision, 1, timestamp, timestamp))
            return self._active(db, variable_id)

    def edit(self, variable_id, expected_version, definition, *, checkpoint=backtest_control.checkpoint):
        """Change the current exact revision; previous revisions remain resolvable."""
        _identifier(variable_id)
        _version(expected_version)
        with self._transaction(write=True, checkpoint=checkpoint) as db:
            record = self._active(db, variable_id, expected_version)
            revision, authored = self._admit(db, variable_id, definition, checkpoint)
            if revision != record['revision']:
                timestamp = _now()
                db.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?)',
                           (variable_id, revision, authored, timestamp))
                db.execute('UPDATE entries SET revision=?,version=version+1,updated_at=? WHERE variable_id=?',
                           (revision, timestamp, variable_id))
            return self._active(db, variable_id)

    def save(self, variable_id, expected_version, name, definition, *, checkpoint=backtest_control.checkpoint):
        """Publish editor name and content together under one optimistic version.

        This shares existing immutable admission and transaction rules. Failure
        publishes neither field; archived dependencies are never imported.
        """
        _identifier(variable_id); _version(expected_version); name = _name(name)
        with self._transaction(write=True, checkpoint=checkpoint) as db:
            record = self._active(db, variable_id, expected_version)
            revision, authored = self._admit(db, variable_id, definition, checkpoint)
            if revision != record['revision'] or name != record['name']:
                timestamp = _now()
                db.execute('INSERT OR IGNORE INTO revisions VALUES(?,?,?,?)',
                           (variable_id, revision, authored, timestamp))
                db.execute('UPDATE entries SET name=?,revision=?,version=version+1,updated_at=? WHERE variable_id=?',
                           (name, revision, timestamp, variable_id))
            return self._active(db, variable_id)

    def _change_metadata(self, variable_id, expected_version, *, name=None, favourite=None,
                         delete=False, checkpoint=backtest_control.checkpoint):
        _identifier(variable_id)
        _version(expected_version)
        with self._transaction(write=True, checkpoint=checkpoint) as db:
            record = self._active(db, variable_id, expected_version)
            values = dict(name=record['name'] if name is None else name,
                          favourite=record['favourite'] if favourite is None else favourite,
                          deleted=delete)
            if any(record[key] != value for key, value in values.items()):
                db.execute('UPDATE entries SET name=?,favourite=?,deleted=?,version=version+1,updated_at=? '
                           'WHERE variable_id=?', (values['name'], int(values['favourite']), int(delete),
                                                  _now(), variable_id))
            return self._metadata(db.execute('SELECT * FROM entries WHERE variable_id=?', (variable_id,)).fetchone())

    def rename(self, variable_id, expected_version, name, *, checkpoint=backtest_control.checkpoint):
        return self._change_metadata(variable_id, expected_version, name=_name(name), checkpoint=checkpoint)

    def favourite(self, variable_id, expected_version, value, *, checkpoint=backtest_control.checkpoint):
        return self._change_metadata(variable_id, expected_version, favourite=_favourite(value), checkpoint=checkpoint)

    def delete(self, variable_id, expected_version, *, checkpoint=backtest_control.checkpoint):
        """Hide the entry. Retain all revisions and its last metadata permanently."""
        return self._change_metadata(variable_id, expected_version, delete=True, checkpoint=checkpoint)

    def resolve(self, roots, *, submitted=None, limits=None, checkpoint=backtest_control.checkpoint):
        """Detach complete exact programs from one snapshot, including deleted revisions.

        This returns the existing FormulaProgram without presentation metadata.
        No later library state is needed by require_program or execution.
        """
        with self._transaction(checkpoint=checkpoint) as db:
            return definitions.resolve(roots, lambda *identity: self._resolve_exact(db, *identity),
                                       submitted=submitted, limits=limits, checkpoint=checkpoint)

    def capture(self, roots, *, submitted=None, labels=None, limits=None,
                checkpoint=backtest_control.checkpoint):
        """Capture exact programs and labels atomically from one read snapshot.

        All definitions use the existing resolver. labels is an optional list
        of {variable_id, revision, name} for submitted identities only; omitted
        labels use the submitted ID. Archive identities use the snapshot's name,
        entry version and deletion status, even when the requested revision is
        old. Favourites are omitted. Submitted content is never persisted.

        limits accepts the existing lowerable definition keys plus
        capture_bytes (default 3 MiB). The returned canonical value retains no
        database handle. Later edits, deletion or file removal cannot affect it.
        Reads require an existing recognized store, including local-only calls.
        """
        with self._transaction(checkpoint=checkpoint) as db:
            return self._capture_snapshot(db, roots, submitted, labels, limits, checkpoint)

    def _capture_snapshot(self, db, roots, submitted, labels, limits, checkpoint):
        formula_limits, bound = _capture_limits(limits)
        archived = set()
        builtins = {}
        def lookup(variable_id, revision):
            definition = self._lookup(db, variable_id, revision)
            if definition is not None:
                archived.add((variable_id, revision))
                return definition
            builtin = measures.exact(variable_id, revision)
            if builtin:
                builtins[variable_id, revision] = builtin['name']
                return builtin['definition']
            return None
        program = definitions.resolve(roots, lookup, submitted=submitted,
                                      limits=formula_limits, checkpoint=checkpoint)
        def metadata(identity):
            row = db.execute('SELECT * FROM entries WHERE variable_id=?', (identity[0],)).fetchone()
            if row is None:
                raise InvalidStore('Variable revision metadata is absent. Its data was kept.')
            return self._metadata(row)
        if labels is not None and type(labels) is not list:
            _capture_error('INVALID_SHAPE', '/labels', 'Labels must name unique submitted definitions only.')
        names = list(labels) if labels is not None else []
        names.extend(dict(variable_id=identity[0], revision=identity[1], name=name)
                     for identity, name in builtins.items())
        return _finish_capture(program, archived, metadata, names, bound, checkpoint)

    def authoring_snapshot(self, exact, *, checkpoint=backtest_control.checkpoint):
        """Read an exact raw closure, capture and entry from one read snapshot.

        The selected revision is separate from entry.revision's current pointer.
        Old and deleted revisions remain readable. Returned content owns no
        connection; callers never reconstruct this operation from public reads.
        """
        if type(exact) is not dict or set(exact) != {'variable_id', 'revision'}:
            raise ValueError('An exact variable revision is required.')
        _identifier(exact['variable_id'])
        with self._transaction(checkpoint=checkpoint) as db:
            captured = self._capture_snapshot(db, [exact], None, None, None, checkpoint)
            authored = []
            for item in captured.to_dict()['program']['bundle']['definitions']:
                checkpoint()
                definition = self._resolve_exact(db, item['variable_id'], item['revision'])
                authored.append(dict(variable_id=item['variable_id'], revision=item['revision'], definition=definition))
            row = db.execute('SELECT * FROM entries WHERE variable_id=?', (exact['variable_id'],)).fetchone()
            if row is None:
                raise InvalidStore('Variable revision metadata is absent. Its data was kept.')
            return dict(entry=self._metadata(row), selected=dict(exact), authored=authored,
                        capture=captured.to_dict())
