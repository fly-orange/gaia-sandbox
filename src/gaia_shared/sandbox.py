import base64
import io
import tarfile
from dataclasses import dataclass

import docker

from .schema import Attachment


@dataclass
class DockerSandbox:
    container: object
    client: object
    timeout: int
    image_id: str = ""
    worker: object | None = None

    def start_tools(self, config: dict, run_dir):
        from .tool_bridge import WorkerConnection

        self.worker = WorkerConnection(
            ["docker", "exec", "-i", self.id, "/opt/gaia/.venv/bin/python", "-m", "gaia_shared.worker"],
            run_dir / "tool-worker.log",
        )
        try:
            return self.worker.call(
                "initialize", config,
                self.timeout + config["sandbox"]["tool_startup_timeout"],
            )
        except BaseException:
            self.worker.close()
            self.worker = None
            raise

    @property
    def id(self):
        return self.container.id

    def execute(self, command: str):
        # GNU timeout runs INSIDE the container, terminating its process group.
        script = (
            "d=$(mktemp -d) || exit 1; trap 'rm -rf -- \"$d\"' EXIT; "
            'timeout --signal=TERM --kill-after=3 "$1" bash -lc "$2" '
            '>"$d/out" 2>"$d/err"; rc=$?; '
            'tail -c 50000 "$d/out"; tail -c 10000 "$d/err" >&2; exit "$rc"'
        )
        result = self.container.exec_run(
            ["bash", "-c", script, "gaia-command", str(self.timeout), command],
            workdir="/workspace",
            user="1000:1000",
            demux=True,
        )
        stdout, stderr = result.output
        return {
            "exit_code": result.exit_code,
            "stdout": (stdout or b"").decode("utf-8", errors="replace")[-50000:],
            "stderr": (stderr or b"").decode("utf-8", errors="replace")[-10000:],
        }

    def upload(self, attachment: Attachment):
        data = base64.b64decode(attachment.data_base64, validate=True)
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tar:
            info = tarfile.TarInfo(attachment.name)
            info.size, info.mode, info.uid, info.gid = len(data), 0o644, 1000, 1000
            tar.addfile(info, io.BytesIO(data))
        if not self.container.put_archive("/workspace", stream.getvalue()):
            raise RuntimeError("Docker attachment upload failed")

    def stats(self):
        data = self.container.stats(stream=False, one_shot=True)
        usage = data.get("cpu_stats", {}).get("cpu_usage", {})
        return {
            "container_id": self.id,
            "image_id": self.image_id,
            "cpu_seconds": usage.get("total_usage", 0) / 1e9,
            "memory_bytes": data.get("memory_stats", {}).get("usage", 0),
            "memory_stats": data.get("memory_stats", {}).get("stats", {}),
            "networks": data.get("networks", {}),
            "blkio": data.get("blkio_stats", {}),
            "pids": data.get("pids_stats", {}).get("current", 0),
        }

    def close(self):
        try:
            if self.worker is not None:
                self.worker.close()
            self.container.remove(force=True)
        finally:
            self.client.close()


class DockerFactory:
    def __init__(self, settings):
        self.settings = settings

    def create(self, run_id):
        s = self.settings
        client = docker.from_env(timeout=s["command_timeout"] + 15)
        container = None
        try:
            # Fail on a missing image, rather than mixing image pulls into measurements.
            image = client.images.get(s["image"])
            container = client.containers.create(
                image.id,
                command=["sleep", "infinity"],
                name=f"gaia-sandbox-{run_id}",
                detach=True,
                init=True,
                user="1000:1000",
                working_dir="/workspace",
                network_mode=s["network"],
                nano_cpus=int(s["cpus"] * 1e9),
                mem_limit=s["memory"],
                memswap_limit=s["memory"],
                pids_limit=s["pids_limit"],
                shm_size=s["shm_size"],
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                labels={"gaia.role": "sandbox", "gaia.run_id": run_id},
                # No Docker socket, model key, HF token or host directories are mounted.
            )
            container.start()
            return DockerSandbox(container, client, s["command_timeout"], image.id)
        except BaseException:
            if container is not None:
                container.remove(force=True)
            client.close()
            raise
