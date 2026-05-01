// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {AccessControl} from "@openzeppelin/contracts/access/AccessControl.sol";

/// @title ProtocolGuardian
/// @notice Minimal on-chain pause registry. Holds a role-gated `paused` flag
///         that a target protocol can read each transaction. The Guardian
///         agent (off-chain) decides when to flip the flag based on its
///         AI classification of pending mempool transactions.
///
///         Two roles exist:
///           - DEFAULT_ADMIN_ROLE  → can grant/revoke GUARDIAN_ROLE
///           - GUARDIAN_ROLE       → can call pause() / unpause()
///
///         Admin is the deployer; admin grants GUARDIAN_ROLE to the agent's
///         hot wallet so the agent can react autonomously without holding
///         admin privileges.
contract ProtocolGuardian is AccessControl {
    bytes32 public constant GUARDIAN_ROLE = keccak256("GUARDIAN_ROLE");

    bool private _paused;
    string public lastReason;
    uint256 public lastUpdate;

    event Paused(address indexed by, string reason);
    event Unpaused(address indexed by);

    error NotGuardian();
    error AlreadyPaused();
    error NotPaused();

    modifier onlyGuardian() {
        if (!hasRole(GUARDIAN_ROLE, msg.sender)) revert NotGuardian();
        _;
    }

    constructor(address admin) {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(GUARDIAN_ROLE, admin);
    }

    /// @notice Read-side check. Target protocols call this in their own
    ///         critical functions (deposit, borrow, withdraw, etc.) to
    ///         circuit-break under attack.
    function paused() external view returns (bool) {
        return _paused;
    }

    /// @notice Pause the protocol. Only callable by an address holding
    ///         GUARDIAN_ROLE — typically the agent's hot wallet.
    /// @param  reason short human-readable label (e.g. function selector,
    ///         confidence bucket, or attack class) recorded for the report.
    function pause(string calldata reason) external onlyGuardian {
        if (_paused) revert AlreadyPaused();
        _paused = true;
        lastReason = reason;
        lastUpdate = block.timestamp;
        emit Paused(msg.sender, reason);
    }

    /// @notice Unpause the protocol. Same role gate.
    function unpause() external onlyGuardian {
        if (!_paused) revert NotPaused();
        _paused = false;
        lastUpdate = block.timestamp;
        emit Unpaused(msg.sender);
    }
}
