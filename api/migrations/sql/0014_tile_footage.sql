-- The number on the tile is the footage. Chosen tiles that leaned on the area's
-- number get it written onto the tile, once. Tiles counted by the piece are left alone.
UPDATE candidate_tags t
SET quantity = a.footage
FROM areas a, candidates c
LEFT JOIN items i ON i.netsuite_id = c.netsuite_item_id AND c.source = 'stock'
WHERE a.id = t.area_id
  AND c.id = t.candidate_id
  AND t.status = 'chosen'
  AND t.quantity IS NULL
  AND a.footage IS NOT NULL
  AND (i.unit IS NULL OR i.unit ~* '^\s*(sf|sq\.? ?ft\.?|sqft|square f)');

-- The area's number is only a starting number now: no source or "how sure" required.
ALTER TABLE areas DROP CONSTRAINT ck_areas_footage_parts;
