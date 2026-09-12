-- Run only during administrator provisioning of the controlled database.
-- The migration owner remains separate and owns all application objects.
CREATE ROLE huron_app_legacy NOLOGIN;
CREATE ROLE huron_app_verified NOLOGIN;
CREATE ROLE huron_cutover NOLOGIN SUPERUSER;

-- Run these grants as the migration owner, after installing schema 0010.
GRANT CONNECT ON DATABASE huron TO huron_app_legacy;
GRANT USAGE ON SCHEMA public TO huron_app_legacy;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO huron_app_legacy;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO huron_app_legacy;

-- Assign passwords through the administrator's secret provisioning channel.
-- Enable only the legacy and cutover logins before starting the legacy service.
-- The verified application role remains disabled until validated activation.
