-- Battles won against other players (attacking or defending), for the battle victory: counted from the reports kept so far.
INSERT INTO player_stats(player_id, stat, value)
SELECT r.player_id, 'pvp_wins', count(*)
FROM reports r
JOIN players me ON me.id = r.player_id AND NOT me.npc AND NOT me.bot
JOIN players other ON other.id = (CASE WHEN (r.data->'attacker'->'player'->>'id')::bigint = r.player_id
                                       THEN r.data->'defender'->'player'->>'id' ELSE r.data->'attacker'->'player'->>'id' END)::bigint
WHERE r.kind = 'battle' AND NOT other.npc AND other.id <> r.player_id
  AND ((r.data->>'winner' = 'attacker' AND (r.data->'attacker'->'player'->>'id')::bigint = r.player_id)
    OR (r.data->>'winner' = 'defender' AND (r.data->'defender'->'player'->>'id')::bigint = r.player_id))
GROUP BY r.player_id
ON CONFLICT (player_id, stat) DO UPDATE SET value = EXCLUDED.value;
