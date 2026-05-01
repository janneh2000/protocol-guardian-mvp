// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IGuardian {
    function paused() external view returns (bool);
}

/// @title MockLendingPool
/// @notice Demo lending pool that consults the off-chain ProtocolGuardian
///         agent (via the on-chain pause flag) before accepting deposits,
///         borrows, or withdrawals. This is the "target protocol" the
///         Guardian agent protects in the demo. Real protocols would wire
///         the same `if (guardian.paused()) revert` check into their own
///         critical paths.
contract MockLendingPool {
    IGuardian public immutable guardian;

    mapping(address => uint256) public deposits;
    uint256 public totalDeposits;
    uint256 public totalBorrowed;

    event Deposited(address indexed user, uint256 amount);
    event Borrowed(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);

    error PoolPaused();
    error InsufficientBalance();
    error InsufficientLiquidity();

    modifier whenLive() {
        if (guardian.paused()) revert PoolPaused();
        _;
    }

    constructor(address guardianAddress) {
        guardian = IGuardian(guardianAddress);
    }

    function deposit() external payable whenLive {
        deposits[msg.sender] += msg.value;
        totalDeposits += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    function borrow(uint256 amount) external whenLive {
        if (totalDeposits - totalBorrowed < amount) revert InsufficientLiquidity();
        totalBorrowed += amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "send fail");
        emit Borrowed(msg.sender, amount);
    }

    function withdraw(uint256 amount) external whenLive {
        if (deposits[msg.sender] < amount) revert InsufficientBalance();
        deposits[msg.sender] -= amount;
        totalDeposits -= amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "send fail");
        emit Withdrawn(msg.sender, amount);
    }

    receive() external payable {}
}
