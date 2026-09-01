why do we need > @translate_db_errors it seems like a bad way test db failures.

What if you use a config value for using a mockdb so that we can
dynamically switch between DB connections in different environments.

local_dev
local_mock
remote_dev
remote_prod

This could be used by the atlasboxpy_db base class.

Also it would be nice to have a way to switch the config based on an API REST header.
This would require an atlasboxpy_api base class.
