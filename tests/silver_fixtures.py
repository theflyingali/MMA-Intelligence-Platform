"""Synthetic landing payloads rich enough for silver: sponsor title, contender series, a cancelled bout,
a draw, a second org, an orphan odds fight. Shaped like the real UFCalendar responses."""

from __future__ import annotations

from typing import Any


def bout(bid: int, a: int, b: int, status: str = "completed", winner: int | None = None,
         method_norm: str | None = "ko_tko", method: str | None = "KO/TKO", rnd: int | None = 2) -> dict[str, Any]:
    result = None if status == "cancelled" else {
        "winner_fighter_id": winner, "method": method, "method_normalized": method_norm, "finish_detail": None,
        "round": rnd, "time": "2:32", "time_seconds": 152, "details": None}
    return {"id": bid, "ordering": 1, "card_section": "main", "sport": "mma", "weight_class": "Welterweight",
            "division_slug": "welterweight", "is_title": False, "is_main": bid % 100 == 0, "scheduled_rounds": 3,
            "status": status, "fighter_a": {"id": a, "slug": f"f{a}", "name": f"Fighter {a}"},
            "fighter_b": {"id": b, "slug": f"f{b}", "name": f"Fighter {b}"}, "result": result,
            "referee": "Ref", "bonus": None}


def event(eid: int, org: str, slug: str, title: str, card: list[dict[str, Any]]) -> dict[str, Any]:
    return {"data": {"id": eid, "slug": slug, "title": title, "short_title": None, "numbering": None, "org": org,
                     "sport": "mma", "starts_at": "2026-10-17T21:00:00.000Z", "main_card_at": "2026-10-18T00:00:00.000Z",
                     "prelims_at": None, "early_prelims_at": None, "tz": "America/Edmonton", "status": "completed",
                     "is_ppv": False, "is_title_card": False,
                     "venue": {"id": 1, "slug": "v", "name": "Arena", "city": "Edmonton", "region": "Alberta",
                               "country": "Canada", "country_code": "CA"},
                     "card": card, "broadcasts": []}, "meta": {}}


def rounds(fight_id: int, a: int, b: int, n_rounds: int = 2) -> dict[str, Any]:
    rows = []
    for rnd in range(1, n_rounds + 1):
        for pos, (fid, corner) in enumerate(((a, "a"), (b, "b")), start=1):
            rows.append({"round_number": rnd, "fighter_id": fid, "fighter_position": pos, "knockdowns": 0,
                         "sig_strikes_landed": 9, "sig_strikes_attempted": 37, "total_strikes_landed": 9,
                         "total_strikes_attempted": 37, "takedowns_landed": 0, "takedowns_attempted": 0,
                         "submission_attempts": 0, "reversals": 0, "control_time_sec": 0, "distance_time_sec": None,
                         "head_landed": None, "corner": corner, "round": rnd})
    return {"data": rows, "meta": {"fight_id": fight_id}}


def side(american: int, dec: float, imp: float) -> dict[str, Any]:
    return {"american": american, "decimal": dec, "implied_probability": imp}


def line(a: int = 106) -> dict[str, Any]:
    return {"a": side(a, 2.06, 0.4854), "b": side(-127, 1.787, 0.5595), "favourite": "b",
            "fair_probability_a": 0.4646, "sources": 18, "recorded_at": "2026-10-17T18:50:29.958Z"}


def odds(eid: int, fights: list[tuple[int, int, int]]) -> dict[str, Any]:
    return {"data": {"event": {"id": eid, "slug": f"ev-{eid}", "org": "ufc", "starts_at": "2026-10-17T21:00:00.000Z"},
                     "fights": [{"fight_id": f, "status": "completed", "fighter_a": {"id": a}, "fighter_b": {"id": b},
                                 "consensus": line(), "opening": line(131), "closing": line(), "movement": {
                                     "delta_points_a": 5.25, "direction": "a"}, "points": 67,
                                 "updated_at": "2026-10-17T18:50:29.958Z", "props": {"method": {}}}
                                for f, a, b in fights]}, "meta": {"priced": len(fights)}}


def record(value: str, w: int, losses: int) -> dict[str, Any]:
    return {"value": value, "wins": w, "losses": losses, "draws": 0, "no_contests": 0, "source": "x", "scope": "s"}


def fighter(fid: int, **over: Any) -> dict[str, Any]:
    data = {"id": fid, "slug": f"f{fid}", "name": f"Fighter {fid}", "nickname": None, "nationality": "Canada",
            "country_code": "CA", "second_nationality": None, "height_inches": 70, "weight_lbs": 170,
            "reach_inches": 72, "stance": "Orthodox", "dob": "1990-05-17", "team": "Gym", "birthplace": "X",
            "records": {"pro_mma": record("6-1-0", 6, 1), "ufc": record("2-1", 2, 1),
                        "amateur_mma": record("3-0", 3, 0)},
            "stats": {"values": {"slpm": 3.13, "str_acc": 0.41, "sapm": 2.2, "str_def": 0.61, "td_avg": 2.0,
                                 "td_acc": 0.5, "td_def": 1.0, "sub_avg": 0.0},
                      "slpm": "3.13", "str_acc": "41%", "basis": {"bouts": 7, "orgs": ["ufc"]}},
            "career_stats": [], "power_index": {"rating": 1691, "peak": 1700, "peak_date": "2026-10-06",
                                                "fights_rated": 7, "last_fought_date": "2026-10-06"},
            "images": [], "next_fight": None,
            "last_fight": {"fight_id": 100, "event_id": 10, "date": "2026-10-06"}}
    data.update(over)
    return {"data": data, "meta": {}}
