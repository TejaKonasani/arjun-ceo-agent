"""Gateway package — MCP gateway + permission matrix."""
from .mcp_gateway import (
    MCPGateway,
    MCP_TOOL_CATALOGUE,
    GatewayDecision,
    GatewayDenialError,
    GatewayApprovalRequired,
)
from .permissions import PERMISSION_MATRIX, authorize_activity, AuthorizationResult
from .handlers import register_default_handlers

__all__ = [
    "register_default_handlers",
    "MCPGateway",
    "MCP_TOOL_CATALOGUE",
    "GatewayDecision",
    "GatewayDenialError",
    "GatewayApprovalRequired",
    "PERMISSION_MATRIX",
    "authorize_activity",
    "AuthorizationResult",
]