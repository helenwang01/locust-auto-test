from __future__ import annotations

from loadtests.longconn.locustfile_chatroom_online_user import (
    resolve_burst_window,
    calculate_target_send_rps,
    is_in_send_window,
    plan_next_send_time,
    resolve_send_window_started_at,
)


def test_is_in_send_window_returns_true_inside_active_window():
    assert is_in_send_window(now_mono=10.0, started_at_mono=0.0, batch_duration_s=30.0, pause_interval_s=300.0) is True


def test_is_in_send_window_returns_false_inside_pause_window():
    assert is_in_send_window(now_mono=45.0, started_at_mono=0.0, batch_duration_s=30.0, pause_interval_s=300.0) is False


def test_is_in_send_window_returns_true_when_next_cycle_starts():
    assert is_in_send_window(now_mono=331.0, started_at_mono=0.0, batch_duration_s=30.0, pause_interval_s=300.0) is True


def test_calculate_target_send_rps_uses_active_send_rate():
    assert calculate_target_send_rps(room_count=10, room_msg_rps=10.0) == 100.0


def test_resolve_send_window_started_at_waits_until_all_joined():
    assert resolve_send_window_started_at(existing_started_at_mono=None, all_joined=False, now_mono=12.0) is None


def test_resolve_send_window_started_at_latches_first_all_joined_moment():
    assert resolve_send_window_started_at(existing_started_at_mono=None, all_joined=True, now_mono=12.0) == 12.0
    assert resolve_send_window_started_at(existing_started_at_mono=12.0, all_joined=True, now_mono=20.0) == 12.0


def test_plan_next_send_time_hits_window_boundary_and_must_not_send():
    first_send_at, first_next_send_at = plan_next_send_time(now_mono=0.0, next_send_at_mono=None, interval_s=1.0)
    assert first_send_at == 0.0
    assert is_in_send_window(now_mono=first_send_at, started_at_mono=0.0, batch_duration_s=1.0, pause_interval_s=60.0) is True

    second_send_at, _ = plan_next_send_time(now_mono=0.0001, next_send_at_mono=first_next_send_at, interval_s=1.0)
    assert second_send_at == 1.0
    assert is_in_send_window(now_mono=second_send_at, started_at_mono=0.0, batch_duration_s=1.0, pause_interval_s=60.0) is False


def test_resolve_burst_window_returns_cycle_boundaries_for_five_minute_pause_model():
    first_cycle = resolve_burst_window(now_mono=0.2, started_at_mono=0.0, batch_duration_s=1.0, pause_interval_s=300.0)
    assert first_cycle.active is True
    assert first_cycle.cycle_index == 0
    assert first_cycle.window_start_mono == 0.0
    assert first_cycle.window_end_mono == 1.0

    pause_cycle = resolve_burst_window(now_mono=120.0, started_at_mono=0.0, batch_duration_s=1.0, pause_interval_s=300.0)
    assert pause_cycle.active is False
    assert pause_cycle.cycle_index == 0
    assert pause_cycle.window_start_mono == 0.0
    assert pause_cycle.window_end_mono == 1.0

    next_cycle = resolve_burst_window(now_mono=301.2, started_at_mono=0.0, batch_duration_s=1.0, pause_interval_s=300.0)
    assert next_cycle.active is True
    assert next_cycle.cycle_index == 1
    assert next_cycle.window_start_mono == 301.0
    assert next_cycle.window_end_mono == 302.0
