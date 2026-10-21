-- A quantity on an order can drop to zero (the customer took it off); the line stays, with its history.
ALTER TABLE estimate_lines DROP CONSTRAINT estimate_lines_quantity_check;
ALTER TABLE estimate_lines ADD CONSTRAINT estimate_lines_quantity_check CHECK (quantity IS NULL OR quantity >= 0);
