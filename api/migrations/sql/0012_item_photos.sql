-- Product photos: the item's image file in NetSuite (custitem_atlas_item_image_2)
-- and the web address of that file, looked up by the item sync.
ALTER TABLE items ADD COLUMN image_file_id INTEGER;
