-- The world as GeoJSON when a round ended, for OpenFantasyMap and other map tools (modules/atlas.py).
ALTER TABLE hall_of_fame ADD COLUMN atlas jsonb;
