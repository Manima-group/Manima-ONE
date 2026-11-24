"""Import every model module so metadata (Alembic, tests) sees all tables and hooks register."""

from manima.core import models as core_models  # noqa: F401
from manima.modules.catalog import module as catalog  # noqa: F401
from manima.modules.compliance_gst import models as gst  # noqa: F401
from manima.modules.crm import module as crm  # noqa: F401
from manima.modules.inventory import module as inventory  # noqa: F401
from manima.modules.invoicing import module as invoicing  # noqa: F401
from manima.modules.payments import module as payments  # noqa: F401
from manima.modules.procurement import module as procurement  # noqa: F401
from manima.modules.sales import module as sales  # noqa: F401
from manima.shared.db import Base

metadata = Base.metadata
