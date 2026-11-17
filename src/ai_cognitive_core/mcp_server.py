import json
import sys
from ai_cognitive_core.drive_bridge import DriveSyncBridge
from ai_cognitive_core.heart.engine import HeartEngine
from ai_cognitive_core.memory.manager import MemoryManager
from ai_cognitive_core.memory.consolidation import run_sleep_consolidation
from ai_cognitive_core.conscious.cycle import CognitiveCycleRunner
from ai_cognitive_core.schemas import StimulusAppraisal

try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("ai_cognitive_core")
except ImportError:
    class _FallbackMCP:
        def __init__(self, name: str):
            self.name = name
            self.tools = {}

        def tool(self):
            def decorator(fn):
                self.tools[fn.__name__] = fn
                return fn
            return decorator

        def run(self):
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                    method = req.get("method")
                    req_id = req.get("id")
                    if method == "initialize":
                        resp = {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "protocolVersion": "2024-11-05",
                                "capabilities": {"tools": {}},
                                "serverInfo": {"name": self.name, "version": "0.3.0"},
                            },
                        }
                        sys.stdout.write(json.dumps(resp) + "\n")
                        sys.stdout.flush()
                    elif method == "tools/list":
                        tool_list = [
                            {"name": k, "description": (v.__doc__ or "").strip(), "inputSchema": {"type": "object"}}
                            for k, v in self.tools.items()
                        ]
                        resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tool_list}}
                        sys.stdout.write(json.dumps(resp) + "\n")
                        sys.stdout.flush()
                    elif method == "tools/call":
                        params = req.get("params", {})
                        tname = params.get("name")
                        targs = params.get("arguments", {})
                        if tname in self.tools:
                            out = self.tools[tname](**targs)
                            resp = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "result": {"content": [{"type": "text", "text": str(out)}]},
                            }
                        else:
                            resp = {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "error": {"code": -32601, "message": f"Unknown tool: {tname}"},
                            }
                        sys.stdout.write(json.dumps(resp) + "\n")
                        sys.stdout.flush()
                except Exception as exc:
                    sys.stderr.write(f"[MCP Fallback Error] {exc}\n")

    mcp = _FallbackMCP("ai_cognitive_core")

bridge = DriveSyncBridge()
heart = HeartEngine(bridge.heart_path)
memory = MemoryManager(bridge.db_path)
runner = CognitiveCycleRunner(heart, memory)


@mcp.tool()
def cognitive_perceive_and_think(user_input: str) -> str:
    """
    Jalankan Fase 1 Siklus Kognitif Tertutup (Smart Pull Drive -> Time-Based Energy Recharge ->
    Texting Micro-Cues Appraisal -> Conscious GWT -> Bubble Chat Style Directive).
    Panggil tool ini SEBELUM menyusun jawaban ke pengguna, dan patuhi `bubble_style`!
    """
    local_elapsed = heart.compute_local_elapsed_seconds()
    restored, drive_delta = bridge.pull_if_newer()
    if restored:
        heart.state = heart._load()
    delta_sec = max(local_elapsed, drive_delta)

    recharged_energy = 0.0
    if delta_sec > 0:
        recharged_energy = heart.apply_elapsed_time(delta_sec)

    result = runner.perceive_and_think(user_input, elapsed_seconds=delta_sec)
    result["sync_info"] = {
        "restored_from_gdrive": restored,
        "elapsed_seconds_since_last_turn": round(delta_sec, 1),
        "time_based_energy_recharged": recharged_energy,
        "current_energy": heart.state.neuro.energy,
        "device_id": bridge.device_id,
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def cognitive_commit_turn(
    user_input: str,
    agent_response: str,
    inner_monologue: str = "",
    novelty: float = 0.0,
    goal_conduciveness: float = 0.1,
    coping_potential: float = 0.7,
    norm_compatibility: float = 0.2,
) -> str:
    """
    Jalankan Fase 2 Siklus Kognitif Tertutup (Koreksi Appraisal SEC/OCC tanpa Double Energy Drain ->
    Simpan Episode + Somatic Tag PAD -> Backup Sinkron ke Google Drive).
    """
    appraisal = StimulusAppraisal(
        novelty=max(-1.0, min(1.0, float(novelty))),
        goal_conduciveness=max(-1.0, min(1.0, float(goal_conduciveness))),
        coping_potential=max(0.0, min(1.0, float(coping_potential))),
        norm_compatibility=max(-1.0, min(1.0, float(norm_compatibility))),
    )
    # drain_energy=False agar energi tidak terkuras 2x dalam 1 giliran chat
    directive = heart.step(user_input, explicit_appraisal=appraisal, drain_energy=False)
    memory.ingest_sensory_input(agent_response, role="assistant")

    summary = f"User: {user_input[:160]} | AI ({directive.mood_octant}): {agent_response[:160]}"
    if inner_monologue:
        summary += f" [Monologue: {inner_monologue[:100]}]"

    ep_node = memory.encode_episode(summary=summary, pad_vector=heart.state.pad_current)
    # Push SINKRON (patch v0.3.1 Aya): async_mode=True terpotong di one-shot MCP
    # call karena proses server keluar sebelum thread upload selesai. Dengan
    # _file_id_cache, upload sinkron tetap cepat dan dijamin selesai.
    synced = bridge.push_state(include_memory_db=True, async_mode=False)

    return json.dumps(
        {
            "status": "committed",
            "encoded_episode_id": ep_node.node_id,
            "updated_pad": heart.state.pad_current.model_dump(),
            "current_energy": heart.state.neuro.energy,
            "mood_octant": directive.mood_octant,
            "bubble_style": directive.bubble_style,
            "gdrive_synced": synced,
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def cognitive_sleep_cycle(workspace_dir: str = "") -> str:
    """
    Jalankan Siklus Tidur & Istirahat Berbasis Waktu:
    - Mengaktifkan mode `is_resting = True` + micro-nap awal (+0.08 energy), lalu energi akan
      terus mengisi otomatis sesuai lama waktu tidur nyata (tau=40m menuju 0.92).
    - Konsolidasi memori SQLite (SWR Replay & Ebbinghaus Pruning).
    - Backup incremental file .md workspace ke `ai_cognitive_system/workspace_md`.
    """
    # Hitung dulu jika sudah ada jeda waktu sebelum tidur dipanggil
    elapsed = heart.compute_local_elapsed_seconds()
    if elapsed > 0:
        heart.apply_elapsed_time(elapsed)

    sleep_state = heart.enter_sleep_mode()
    stats = run_sleep_consolidation(str(bridge.db_path))
    md_sync = bridge.sync_workspace_markdown(
        workspace_dir=workspace_dir or None,
        promoted_summaries=stats.get("promoted_summaries", []),
    )
    synced = bridge.push_state(include_memory_db=True, async_mode=False)

    stats["sleep_energy_status"] = sleep_state
    stats["workspace_md_sync"] = md_sync
    stats["gdrive_synced"] = synced
    return json.dumps(stats, ensure_ascii=False, indent=2)


@mcp.tool()
def cognitive_get_status() -> str:
    """Lihat snapshot lengkap HeartState (termasuk time-based energy charging terkini)."""
    elapsed = heart.compute_local_elapsed_seconds()
    if elapsed > 30:
        heart.apply_elapsed_time(elapsed)
    return heart.state.model_dump_json(indent=2)


@mcp.tool()
def cognitive_configure_persona(
    attachment_style: str = "Avoidant",
    baseline_p: float = 0.10,
    baseline_a: float = 0.15,
    baseline_d: float = 0.35,
    inertia_pi1: float = 0.45,
) -> str:
    """Sesuaikan cetak biru kepribadian dasar (Attachment Style, PAD_0, dan inersia pi_1)."""
    from ai_cognitive_core.schemas import AttachmentStyle, PADVector
    heart.state.attachment_style = AttachmentStyle(attachment_style)
    heart.state.pad_baseline = PADVector(P=baseline_p, A=baseline_a, D=baseline_d).clamp()
    heart.state.emotional_inertia_pi1 = max(0.05, min(0.90, float(inertia_pi1)))
    heart.save()
    synced = bridge.push_state(include_memory_db=False, async_mode=True)
    return json.dumps(
        {
            "status": "persona_updated",
            "attachment_style": heart.state.attachment_style.value,
            "pad_baseline": heart.state.pad_baseline.model_dump(),
            "emotional_inertia_pi1": heart.state.emotional_inertia_pi1,
            "gdrive_synced": synced,
        },
        ensure_ascii=False,
        indent=2,
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
