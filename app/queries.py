"""SQL for the dashboard. Read-only, parameterised, and small: every query is a key lookup or a capped scan
of a table under 60k rows. Only `mma.silver` is read (catalog and schema are set by the client).

Corner columns (`fighter_a_*`, `fighter_b_*`, `corner_reliable`) are selected only to work out the
opponent and to decide whether corner order may be shown; see `display.py`.
"""

# One row per fighter with the organisations they fought in ('dwcs' kept apart from 'ufc').
# About 5,300 rows, loaded once per cache period so search never queries per keystroke.
FIGHTER_INDEX = """
SELECT f.fighter_id, f.name, f.nickname, f.country_code,
       array_join(array_sort(collect_set(CASE WHEN fb.is_contender_series THEN 'dwcs' ELSE fb.org END)), ',') AS orgs,
       count(fb.bout_id) AS bouts,
       max(fb.event_starts_at) AS last_bout_at
FROM fighter f
LEFT JOIN fighter_bout fb ON fb.fighter_id = f.fighter_id
GROUP BY f.fighter_id, f.name, f.nickname, f.country_code
LIMIT 20000
"""

# Events, without those the source marks completed but whose title says cancelled or postponed.
EVENTS = """
SELECT e.event_id, e.org, e.title_clean, e.starts_at, e.venue_name, e.venue_city, e.venue_country,
       e.is_contender_series, e.is_official_ufc, e.is_ppv, coalesce(b.played, 0) AS played_bouts
FROM event e
LEFT JOIN (SELECT event_id, count(*) AS played FROM bout WHERE outcome <> 'cancelled' GROUP BY event_id) b
  ON b.event_id = e.event_id
WHERE NOT coalesce(e.title_says_cancelled, false)
ORDER BY e.starts_at DESC
LIMIT 5000
"""

EVENT_BOUTS = """
SELECT b.bout_id, b.ordering, b.card_section, b.sport, b.weight_class, b.is_title, b.is_main,
       b.scheduled_rounds, b.outcome, b.fighter_a_id, b.fighter_a_name, b.fighter_b_id, b.fighter_b_name,
       b.winner_fighter_id, b.method, b.method_normalized, b.finish_detail, b.end_round, b.end_time,
       b.bonus, b.corner_reliable, rs.fight_id IS NOT NULL AS has_round_stats
FROM bout b
LEFT JOIN (SELECT DISTINCT fight_id FROM round_stats
           WHERE fight_id IN (SELECT bout_id FROM bout WHERE event_id = :event_id)) rs
  ON rs.fight_id = b.bout_id
WHERE b.event_id = :event_id
ORDER BY b.ordering, b.bout_id
LIMIT 200
"""

FIGHTER = """
SELECT fighter_id, name, nickname, nationality, country_code, height_cm, reach_cm, weight_lbs, stance, dob,
       team, birthplace,
       pro_mma_wins, pro_mma_losses, pro_mma_draws, pro_mma_no_contests,
       ufc_wins, ufc_losses, ufc_draws, ufc_no_contests,
       slpm, str_acc, sapm, str_def, td_avg, td_acc, td_def, sub_avg, stats_bouts
FROM fighter
WHERE fighter_id = :fighter_id
"""

FIGHTER_RECORDS = """
SELECT record_type, wins, losses, draws, no_contests
FROM fighter_record
WHERE fighter_id = :fighter_id
ORDER BY record_type
LIMIT 50
"""

# Read from `bout`, not `fighter_bout`, so the one bout with outcome 'unknown' (which fighter_bout leaves
# out) still appears, and names and method come without extra joins.
FIGHTER_HISTORY = """
SELECT b.bout_id, b.event_id, e.title_clean AS event_title, b.org, b.is_contender_series, b.event_starts_at,
       b.sport, b.weight_class, b.is_title, b.outcome, b.fighter_a_id, b.fighter_a_name, b.fighter_b_id,
       b.fighter_b_name, b.winner_fighter_id, b.method, b.method_normalized, b.finish_detail, b.end_round,
       b.end_time
FROM bout b
LEFT JOIN event e ON e.event_id = b.event_id
WHERE (b.fighter_a_id = :fighter_id OR b.fighter_b_id = :fighter_id) AND b.outcome <> 'cancelled'
ORDER BY b.event_starts_at DESC, b.ordering
LIMIT 500
"""

FIGHT = """
SELECT b.bout_id, b.event_id, e.title_clean AS event_title, b.org, b.is_contender_series, b.event_starts_at,
       e.venue_city, e.venue_country, b.sport, b.weight_class, b.is_title, b.is_main, b.scheduled_rounds,
       b.outcome, b.fighter_a_id, b.fighter_a_name, b.fighter_b_id, b.fighter_b_name, b.winner_fighter_id,
       b.method, b.method_normalized, b.finish_detail, b.end_round, b.end_time, b.referee, b.bonus,
       b.corner_reliable
FROM bout b
LEFT JOIN event e ON e.event_id = b.event_id
WHERE b.bout_id = :bout_id
"""

ROUND_STATS = """
SELECT round_number, fighter_id, knockdowns, sig_strikes_landed, sig_strikes_attempted,
       total_strikes_landed, total_strikes_attempted, takedowns_landed, takedowns_attempted,
       submission_attempts, reversals, control_time_sec,
       head_landed, head_attempted, body_landed, body_attempted, leg_landed, leg_attempted
FROM round_stats
WHERE fight_id = :bout_id
ORDER BY round_number, fighter_position
LIMIT 100
"""

# When the source was last fetched, for the "data last updated" note in the footer. One row.
FRESHNESS = """
SELECT max(fetched_at) AS fetched_at
FROM event
"""
