// Hardhat deploy script — Sepolia.
//
// Deploys ProtocolGuardian → MockLendingPool, grants GUARDIAN_ROLE on the
// registry to the agent's hot wallet, and writes both addresses to
// addresses.json so the agent can pick them up at startup.
//
// Run:
//   npx hardhat run scripts/deploy.js --network sepolia

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  console.log(`Deploying with: ${deployer.address}`);
  console.log(`Network:        ${hre.network.name}`);

  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log(`Balance:        ${hre.ethers.formatEther(balance)} ETH\n`);

  // 1. Deploy the pause registry. Admin = deployer.
  console.log("→ deploying ProtocolGuardian…");
  const Guardian = await hre.ethers.getContractFactory("ProtocolGuardian");
  const guardian = await Guardian.deploy(deployer.address);
  await guardian.waitForDeployment();
  const guardianAddr = await guardian.getAddress();
  console.log(`  ✓ ProtocolGuardian: ${guardianAddr}`);

  // 2. Deploy the demo pool, wired to the registry.
  console.log("→ deploying MockLendingPool…");
  const Pool = await hre.ethers.getContractFactory("MockLendingPool");
  const pool = await Pool.deploy(guardianAddr);
  await pool.waitForDeployment();
  const poolAddr = await pool.getAddress();
  console.log(`  ✓ MockLendingPool:  ${poolAddr}`);

  // 3. Grant GUARDIAN_ROLE to the agent's hot wallet so it can call pause().
  const hotKey = process.env.GUARDIAN_HOT_WALLET_PRIVATE_KEY;
  if (hotKey) {
    const hotWallet = new hre.ethers.Wallet(hotKey);
    const role = await guardian.GUARDIAN_ROLE();
    console.log(`→ granting GUARDIAN_ROLE to ${hotWallet.address}…`);
    const tx = await guardian.grantRole(role, hotWallet.address);
    await tx.wait();
    console.log(`  ✓ role granted (tx ${tx.hash})`);
  } else {
    console.log("⚠  GUARDIAN_HOT_WALLET_PRIVATE_KEY unset — skipping role grant.");
    console.log("   Set it in .env and re-run, or grant the role manually later.");
  }

  // 4. Write addresses.json so main.py can find the deployment.
  const addresses = {
    network: hre.network.name,
    chainId: Number((await hre.ethers.provider.getNetwork()).chainId),
    deployer: deployer.address,
    ProtocolGuardian: guardianAddr,
    MockLendingPool: poolAddr,
    deployedAt: new Date().toISOString(),
  };
  const out = path.join(__dirname, "..", "addresses.json");
  fs.writeFileSync(out, JSON.stringify(addresses, null, 2));
  console.log(`\nWrote ${out}`);
  console.log("\nNext: copy GUARDIAN_CONTRACT_ADDRESS into .env (or rely on addresses.json)");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
