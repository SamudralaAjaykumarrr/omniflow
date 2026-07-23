-- Runs once, on first container start, via /docker-entrypoint-initdb.d.
-- Each service owns its own database (see docs/adrs/0008-monorepo-layout.md)
-- — no cross-service foreign keys at the SQL level. A *_test database per
-- service keeps test runs from touching dev data.
CREATE DATABASE omniflow_orders;
CREATE DATABASE omniflow_orders_test;
CREATE DATABASE omniflow_inventory;
CREATE DATABASE omniflow_inventory_test;
