import json
import sys
from typing import Optional
from ai_cognitive_core import config
from ai_cognitive_core.drive_bridge import DriveSyncBridge
from ai_cognitive_core.heart.engine import HeartEngine
from ai_cognitive_core.heart.layers.l1_neurochemical import current_local_hour, get_circadian_phase
from ai_cognitive_core.heart.layers.l3_mood_space import detect_coactivation
from ai_cognitive_core.heart import phrase_bank
from ai_cognitive_core.memory.manager import MemoryManager
from ai_cognitive_core.memory.consolidation import run_sleep_consolidation
from ai_cognitive_core.memory import migration
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
                                "serverInfo": {"name": self.name, "version": "0.5.0"},
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
def cognitive_perceive_and_think(user_input: str, turn_id: str = "") -> str:
    """
    Jalankan Fase 1 Siklus Kognitif Tertutup (Smart Pull Drive -> Time-Based Energy Recharge ->
    Texting Micro-Cues Appraisal -> Conscious GWT -> Bubble Chat Style Directive).
    Panggil tool ini SEBELUM menyusun jawaban ke pengguna, dan patuhi `bubble_style`!

    v0.4.0: turn_id opsional mengaitkan perceive<->commit; retry perceive dengan
    turn_id yang sama tidak menguras energi dua kali. Hasil dapat memuat
    curiosity_prompt, proactive_intent, dream_idea, photo_reference (maks 1
    masing-masing) dan diagnostics.
    """
    local_elapsed = heart.compute_local_elapsed_seconds()
    restored, drive_delta = bridge.pull_if_newer()
    if restored:
        heart.state = heart._load()
    delta_sec = max(local_elapsed, drive_delta)

    recharged_energy = 0.0
    if delta_sec > 0:
        recharged_energy = heart.apply_elapsed_time(delta_sec)
        # v0.4.0: telemetri isi ulang (tanpa konten percakapan).
        if recharged_energy != 0.0:
            memory.record_energy_telemetry(
                turn_id=turn_id or None,
                recharge=recharged_energy,
                energy_after=heart.state.neuro.energy,
                noradrenaline=heart.state.neuro.noradrenaline,
                cortisol=heart.state.neuro.cortisol,
            )

    result = runner.perceive_and_think(user_input, elapsed_seconds=delta_sec, turn_id=turn_id or None)
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
    novelty: Optional[float] = None,
    goal_conduciveness: Optional[float] = None,
    coping_potential: Optional[float] = None,
    norm_compatibility: Optional[float] = None,
    # --- v0.4.0: semua parameter baru opsional (kompatibel ke belakang) ---
    turn_id: str = "",
    propose_question: Optional[dict] = None,
    create_reminder: Optional[dict] = None,
    photo_moment: Optional[dict] = None,
    curiosity_asked_id: str = "",
    dismiss_curiosity_id: str = "",
    dismiss_dream_id: str = "",
    reminder_id: str = "",
    reminder_action: str = "",
    snooze_until: str = "",
    photo_moment_id: str = "",
    photo_moment_action: str = "",
    photo_moment_correction: Optional[dict] = None,
    # --- v0.4.1/v0.5.0: parameter opsional (100% kompatibel ke belakang) ---
    learn_habit: Optional[dict] = None,
    habit_feedback: Optional[dict] = None,
    worker_task: Optional[dict] = None,
    add_inside_joke: Optional[dict] = None,
) -> str:
    """
    Jalankan Fase 2 Siklus Kognitif Tertutup (Koreksi Appraisal SEC/OCC tanpa Double Energy Drain ->
    Simpan Episode + Somatic Tag PAD -> Backup Sinkron ke Google Drive).

    v0.4.0: turn_id yang sama dengan perceive mengaitkan giliran; commit duplikat
    ditolak tanpa menulis ulang. Parameter opsional lain menggerakkan fitur baru:
    propose_question {text, topic, priority, context_tags, expires_at},
    create_reminder {text, due_at, trigger_condition, priority, repeat_policy},
    photo_moment {caption, people, place, event_tags, source_ref,
    consent_status, timestamp} — caption eksplisit saja, modul tidak melihat gambar.
    Aksi: curiosity_asked_id, dismiss_curiosity_id, dismiss_dream_id,
    reminder_id + reminder_action (complete|snooze|dismiss) + snooze_until,
    photo_moment_id + photo_moment_action (correct|delete) + photo_moment_correction.
    """
    # v0.4.0: tolak commit duplikat SEBELUM heart.step agar appraisal tidak
    # dikoreksi dua kali untuk giliran yang sama.
    if turn_id:
        marker = memory.get_turn_marker(turn_id)
        if marker and marker["phase"] == "committed":
            return json.dumps(
                {
                    "status": "duplicate_commit",
                    "encoded_episode_id": marker["episode_id"],
                    "current_energy": heart.state.neuro.energy,
                    "mood_octant": heart.state.pad_current.octant_label(),
                    "gdrive_synced": False,
                },
                ensure_ascii=False,
                indent=2,
            )

    has_explicit_appraisal = any(
        v is not None for v in (novelty, goal_conduciveness, coping_potential, norm_compatibility)
    )
    if has_explicit_appraisal:
        appraisal = StimulusAppraisal(
            novelty=max(-1.0, min(1.0, float(0.0 if novelty is None else novelty))),
            goal_conduciveness=max(-1.0, min(1.0, float(0.0 if goal_conduciveness is None else goal_conduciveness))),
            coping_potential=max(0.0, min(1.0, float(0.5 if coping_potential is None else coping_potential))),
            norm_compatibility=max(-1.0, min(1.0, float(0.0 if norm_compatibility is None else norm_compatibility))),
        )
        directive = heart.step(user_input, explicit_appraisal=appraisal, drain_energy=False)
    else:
        dom, sec = detect_coactivation(heart.state.primary_affects)
        directive = heart.build_directive(dom, sec)
    memory.ingest_sensory_input(agent_response, role="assistant")

    summary = f"User: {user_input[:160]} | AI ({directive.mood_octant}): {agent_response[:160]}"
    if inner_monologue:
        summary += f" [Monologue: {inner_monologue[:100]}]"

    # v0.4.0: episode + penanda giliran + aksi v0.4.0 dalam SATU transaksi.
    actions = {
        "propose_question": propose_question,
        "create_reminder": create_reminder,
        "photo_moment": photo_moment,
        "curiosity_asked_id": curiosity_asked_id,
        "dismiss_curiosity_id": dismiss_curiosity_id,
        "dismiss_dream_id": dismiss_dream_id,
        "reminder_id": reminder_id,
        "reminder_action": reminder_action,
        "snooze_until": snooze_until,
        "photo_moment_id": photo_moment_id,
        "photo_moment_action": photo_moment_action,
        "photo_moment_correction": photo_moment_correction,
    }
    bundle = memory.commit_turn_bundle(
        summary, heart.state.pad_current, turn_id=turn_id or None, actions=actions
    )
    if bundle.get("duplicate"):
        return json.dumps(
            {
                "status": "duplicate_commit",
                "encoded_episode_id": bundle.get("episode_id"),
                "current_energy": heart.state.neuro.energy,
                "mood_octant": directive.mood_octant,
                "gdrive_synced": False,
            },
            ensure_ascii=False,
            indent=2,
        )

    # v0.4.1/v0.5.0: adaptasi L5, worker blackboard, & inside jokes
    v050_outcomes = {}
    if isinstance(learn_habit, dict) and learn_habit.get("trigger_pattern") and learn_habit.get("action_template"):
        v050_outcomes["habit_learned"] = memory.learn_procedural_habit(
            learn_habit.get("trigger_pattern", ""),
            learn_habit.get("action_template", ""),
        )
    if isinstance(habit_feedback, dict) and habit_feedback.get("habit_id"):
        v050_outcomes["habit_reinforced"] = memory.reinforce_procedural_habit(
            habit_feedback["habit_id"],
            delta=int(habit_feedback.get("delta", 1)),
        )
    if isinstance(worker_task, dict) and worker_task.get("worker_name"):
        wt_res = memory.upsert_worker_task(
            worker_name=worker_task.get("worker_name", ""),
            description=worker_task.get("description", ""),
            status=worker_task.get("status", "pending"),
            result_summary=worker_task.get("result_summary", ""),
            task_id=worker_task.get("task_id"),
        )
        v050_outcomes["worker_task"] = wt_res
        if wt_res.get("stored") and wt_res.get("status") in {"done", "failed"}:
            heart.apply_worker_outcome(wt_res["status"])
    if isinstance(add_inside_joke, dict) and add_inside_joke.get("phrase"):
        v050_outcomes["inside_joke"] = memory.add_inside_joke(
            phrase=add_inside_joke.get("phrase", ""),
            meaning=add_inside_joke.get("meaning", ""),
            trigger_keywords=add_inside_joke.get("trigger_keywords"),
        )

    critical_energy = heart.state.neuro.energy <= getattr(config, "DRIVE_CRITICAL_ENERGY_THRESHOLD", 0.10)
    push_db = getattr(config, "DRIVE_PUSH_DB_ON_COMMIT", False) or critical_energy
    synced = bridge.push_state(include_memory_db=push_db, async_mode=False)

    return json.dumps(
        {
            "status": "committed",
            "encoded_episode_id": bundle["episode_id"],
            "updated_pad": heart.state.pad_current.model_dump(),
            "current_energy": heart.state.neuro.energy,
            "mood_octant": directive.mood_octant,
            "bubble_style": directive.bubble_style,
            "gdrive_synced": synced,
            "gdrive_db_included": push_db,
            "v040_outcomes": bundle.get("outcomes", {}),
            "v050_outcomes": v050_outcomes,
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
    """Lihat snapshot lengkap HeartState (termasuk time-based energy charging terkini).

    v0.4.0: ditambah kunci "v040" berisi hitungan fitur (tanpa isi pribadi),
    ringkasan telemetri energi, flag fitur, dan versi skema.
    """
    elapsed = heart.compute_local_elapsed_seconds()
    if elapsed > 30:
        heart.apply_elapsed_time(elapsed)
    snapshot = heart.state.model_dump()
    snapshot["v040"] = {
        "counts": memory.v040_counts(),
        "energy_telemetry": memory.telemetry_summary(),
        "schema_version": migration.get_schema_version(str(bridge.db_path)),
        "phrase_bank_version": phrase_bank.PHRASE_BANK_VERSION,
        "features_enabled": {
            "curiosity": config.ENABLE_CURIOSITY,
            "reminders": config.ENABLE_REMINDERS,
            "dreams": config.ENABLE_DREAMS,
            "photo_memory": config.ENABLE_PHOTO_MEMORY,
            "phrase_bank": config.ENABLE_PHRASE_BANK,
            "energy_telemetry": config.ENABLE_ENERGY_TELEMETRY,
        },
    }
    local_hour = current_local_hour()
    snapshot["v050"] = {
        "core_version": "0.5.0",
        "circadian": {"local_hour": local_hour, "phase": get_circadian_phase(local_hour)},
        "relationship": {
            "trust_score": heart.state.trust_score,
            "stage": heart.state.relationship_stage,
        },
        "working_memory_chunks": len(memory.working.active_pages),
        "worker_blackboard": memory.list_worker_tasks(limit=10, only_active=False),
        "proactive_heartbeat": memory.evaluate_idle_heartbeat(
            elapsed_seconds=elapsed,
            energy=heart.state.neuro.energy,
            is_resting=heart.state.is_resting,
            local_hour=local_hour,
        ),
    }
    return json.dumps(snapshot, ensure_ascii=False, indent=2)


@mcp.tool()
def cognitive_configure_persona(
    attachment_style: str = "Avoidant",
    baseline_p: float = 0.05,
    baseline_a: float = -0.05,
    baseline_d: float = 0.15,
    inertia_pi1: float = 0.45,
) -> str:
    """Sesuaikan cetak biru kepribadian dasar (Attachment Style, PAD_0, dan inersia pi_1)."""
    from ai_cognitive_core.schemas import AttachmentStyle, PADVector
    heart.state.attachment_style = AttachmentStyle(attachment_style)
    heart.state.pad_baseline = PADVector(P=baseline_p, A=baseline_a, D=baseline_d).clamp()
    heart.state.emotional_inertia_pi1 = max(0.05, min(0.90, float(inertia_pi1)))
    heart.save()
    synced = bridge.push_state(include_memory_db=False, async_mode=False)
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
