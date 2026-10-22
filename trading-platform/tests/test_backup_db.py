from dataclasses import dataclass

from scripts.backup_db import _prune_old_dumps


@dataclass
class FakeObject:
    name: str


class FakeStorage:
    def __init__(self, names, sizes):
        self.objects = {name: FakeObject(name) for name in names}
        self.sizes = sizes
        self.deleted = []

    def list(self, prefix):
        return [obj for name, obj in self.objects.items() if name.startswith(prefix)]

    def get_size(self, name):
        return self.sizes.get(name)

    def delete(self, name, ignore_not_found=False):
        self.deleted.append(name)
        self.objects.pop(name, None)


def test_pruning_does_not_delete_when_twelve_or_fewer():
    names = [f"backups/quant-terminal/2026-10-{day:02d}_0300.dump" for day in range(1, 13)]
    storage = FakeStorage(names, {names[-1]: 100})

    removed = _prune_old_dumps(storage, "backups/quant-terminal/", names[-1], 100)

    assert removed == []
    assert storage.deleted == []


def test_pruning_waits_until_new_upload_is_confirmed_with_matching_size():
    names = [f"backups/quant-terminal/2026-10-{day:02d}_0300.dump" for day in range(1, 14)]
    storage = FakeStorage(names, {names[-1]: 99})

    removed = _prune_old_dumps(storage, "backups/quant-terminal/", names[-1], 100)

    assert removed == []
    assert storage.deleted == []


def test_pruning_deletes_only_oldest_dumps_beyond_retention():
    from scripts.backup_db import RETENTION_DUMPS
    names = [f"backups/quant-terminal/2026-10-{day:02d}_0300.dump" for day in range(1, RETENTION_DUMPS + 2)]
    names += [f"{name}.sha256" for name in names]
    newest = f"backups/quant-terminal/2026-10-{RETENTION_DUMPS + 1:02d}_0300.dump"
    storage = FakeStorage(names, {newest: 100})

    removed = _prune_old_dumps(
        storage,
        "backups/quant-terminal/",
        newest,
        100,
    )

    assert removed == ["backups/quant-terminal/2026-10-01_0300.dump"]
    assert storage.deleted == [
        "backups/quant-terminal/2026-10-01_0300.dump",
        "backups/quant-terminal/2026-10-01_0300.dump.sha256",
    ]
