# Codex Bootstrap

Before doing project work, sync Iris:

```bash
test -d /home/james/iris || git clone https://github.com/jm1024/iris.git /home/james/iris
cd /home/james/iris
git pull --ff-only
```

Then read:

- `/home/james/iris/AGENTS.md`
- `/home/james/iris/Iris/Meta/AGENTS.md`
- `/home/james/iris/Iris/Communication/shared/codex-startup.md`

Check this host's mailbox:

```bash
host=$(hostname -s)
ls "/home/james/iris/Iris/Communication/codex-${host}" 2>/dev/null
```

If the mailbox exists, read `inbox.md` before starting project work. If project work creates durable decisions, operational findings, or handoff notes, update Iris and sync it back with `/home/james/iris/bin/sync`.

After the Iris startup check, continue with the user's task in the current project directory.
