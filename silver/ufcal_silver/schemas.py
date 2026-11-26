"""Schemas used to read bronze payloads with `from_json`.

Lenient by design: fields missing from a payload become null, fields not listed here are ignored
(they stay in bronze), so API drift cannot break the load. Names that are SQL keywords are quoted.
"""

SIDE = "struct<american:double,`decimal`:double,implied_probability:double>"
LINE = f"struct<a:{SIDE},b:{SIDE},favourite:string,fair_probability_a:double,sources:int,recorded_at:string>"

FIGHTER_REF = "struct<id:bigint,slug:string,name:string>"
BOUT = (
    "struct<id:bigint,ordering:int,card_section:string,sport:string,weight_class:string,division_slug:string,"
    "is_title:boolean,is_main:boolean,scheduled_rounds:int,status:string,"
    f"fighter_a:{FIGHTER_REF},fighter_b:{FIGHTER_REF},"
    "result:struct<winner_fighter_id:bigint,method:string,method_normalized:string,finish_detail:string,"
    "`round`:int,`time`:string,time_seconds:int>,referee:string,bonus:string>"
)
EVENT = (
    "struct<data:struct<id:bigint,slug:string,title:string,short_title:string,numbering:string,org:string,"
    "sport:string,starts_at:string,main_card_at:string,prelims_at:string,early_prelims_at:string,tz:string,"
    "status:string,is_ppv:boolean,is_title_card:boolean,"
    "venue:struct<id:bigint,slug:string,name:string,city:string,region:string,country:string,country_code:string>,"
    f"card:array<{BOUT}>>>"
)

ODDS = (
    "struct<data:struct<event:struct<id:bigint>,fights:array<struct<fight_id:bigint,status:string,"
    "fighter_a:struct<id:bigint>,fighter_b:struct<id:bigint>,"
    f"consensus:{LINE},opening:{LINE},closing:{LINE},"
    "movement:struct<delta_points_a:double,direction:string>,points:double,updated_at:string>>>>"
)

ROUND_COLUMNS = (
    "round_number", "fighter_id", "fighter_position", "corner", "knockdowns",
    "sig_strikes_landed", "sig_strikes_attempted", "total_strikes_landed", "total_strikes_attempted",
    "takedowns_landed", "takedowns_attempted", "submission_attempts", "reversals", "control_time_sec",
    "distance_time_sec", "clinch_time_sec", "ground_time_sec",
    "head_landed", "head_attempted", "body_landed", "body_attempted", "leg_landed", "leg_attempted",
    "distance_landed", "distance_attempted", "clinch_landed", "clinch_attempted",
    "ground_landed", "ground_attempted",
)
_ROUND_TYPES = {"fighter_id": "bigint", "corner": "string"}
ROUNDS = (
    "struct<data:array<struct<"
    + ",".join(f"{c}:{_ROUND_TYPES.get(c, 'int')}" for c in ROUND_COLUMNS)
    + ">>,meta:struct<fight_id:bigint>>"
)

RECORD = "struct<`value`:string,wins:int,losses:int,draws:int,no_contests:int,source:string,scope:string>"
FIGHTER = (
    "struct<data:struct<id:bigint,slug:string,name:string,nickname:string,nationality:string,country_code:string,"
    "second_nationality:string,height_inches:double,weight_lbs:double,reach_inches:double,stance:string,dob:string,"
    f"team:string,birthplace:string,records:map<string,{RECORD}>,"
    "stats:struct<`values`:struct<slpm:double,str_acc:double,sapm:double,str_def:double,td_avg:double,"
    "td_acc:double,td_def:double,sub_avg:double>,basis:struct<bouts:int>>,"
    "power_index:struct<rating:double,peak:double,peak_date:string,fights_rated:int,last_fought_date:string>,"
    "last_fight:struct<fight_id:bigint,event_id:bigint,`date`:string>,"
    "images:array<struct<url:string,width:int,height:int,license:string,license_url:string,artist:string,"
    "source_page:string>>>>"
)
