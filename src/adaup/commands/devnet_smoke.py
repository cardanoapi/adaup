#!/usr/bin/env python
"""
Governance smoke test / seeder for the docker devnet.

Runs cardano-cli inside the running cardano-node container (so the host only
needs docker) and exercises the full Conway governance surface:

  stake registration, DRep registration / update / retirement (with anchors),
  vote delegation to a DRep, always-abstain and always-no-confidence,
  constitutional committee hot key authorisation, one proposal of every type,
  and DRep / SPO / CC votes on them.

Setup steps are idempotent (they check the ledger first); every run creates a
fresh set of proposals, so it can also be used to seed a devnet with live
governance actions. Keys, anchors and transactions are kept under
<devnet dir>/smoke and <devnet dir>/anchors, and a summary with proposal ids
and timings is written to <devnet dir>/smoke/result.json.
"""

import json
import os
import shlex
import time

from adaup.commands.devnet_docker import (
    ADA,
    DEVNET_MAGIC,
    blake2b_256,
    compose,
    require_docker,
)

ALL_ACTIONS = ["info", "treasury", "parameter", "hardfork", "no-confidence", "committee", "constitution"]
DEFAULT_RATIFY = ["treasury", "parameter", "committee", "constitution"]

# Which voter roles may vote on each action (Conway ledger rules). SPOs only
# vote on security-group parameters; the parameter change used here
# (treasury expansion) is in the economic group.
ELIGIBLE_VOTERS = {
    "info": ("drep", "spo", "cc"),
    "treasury": ("drep", "cc"),
    "parameter": ("drep", "cc"),
    "hardfork": ("drep", "spo", "cc"),
    "no-confidence": ("drep", "spo"),
    "committee": ("drep", "spo"),
    "constitution": ("drep", "cc"),
}

# Ledger purpose key used for the previous-action chain of each action type.
PREV_PURPOSE = {
    "parameter": "PParamUpdate",
    "hardfork": "HardFork",
    "no-confidence": "Committee",
    "committee": "Committee",
    "constitution": "Constitution",
}

WALLET_FUNDS_ADA = {
    "proposer": 2_000_000,   # pays proposal deposits and fees; delegates to drep1
    "abstainer": 1_000,      # delegates to always-abstain
    "no-confidence": 1_000,  # delegates to always-no-confidence
    "retiring": 1_000,       # delegates to drep2, which then retires
}

TREASURY_WITHDRAWAL_ADA = 1_000
C_ROOT = "/devnet"


def log(message=""):
    print(message, flush=True)


class Smoke:
    def __init__(self, settings):
        self.settings = settings
        self.host_dir = os.path.join(settings.dir, "smoke")
        self.anchor_dir = os.path.join(settings.dir, "anchors")
        os.makedirs(self.host_dir, exist_ok=True)
        os.makedirs(self.anchor_dir, exist_ok=True)
        self.timings = {}
        self.anchor_base = os.environ.get("ADAUP_DEVNET_ANCHOR_BASE_URL", "http://anchors:8080").rstrip("/")

    # -- paths ---------------------------------------------------------------

    def c(self, *parts):
        """Container path under the smoke dir."""
        return "/".join([C_ROOT, "smoke", *parts])

    def h(self, *parts):
        """Host path under the smoke dir."""
        return os.path.join(self.host_dir, *parts)

    # -- running commands ----------------------------------------------------

    def bash(self, script, check=True):
        result = compose(
            self.settings, "exec", "-T", "cardano-node", "bash", "-euo", "pipefail", "-c", script,
            check=False, capture=True,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"command failed:\n{script}\n{(result.stderr or result.stdout).strip()}")
        return result.stdout.strip()

    def cli(self, *args, check=True):
        return self.bash(_cmd("cardano-cli", *args), check=check)

    def query(self, *args):
        output = self.cli("conway", "query", *args, "--testnet-magic", str(DEVNET_MAGIC))
        return json.loads(output) if output else None

    def tip(self):
        return self.query("tip")

    def pparams(self):
        return self.query("protocol-parameters")

    def psql(self, sql):
        s = self.settings
        result = compose(
            s, "exec", "-T", "postgres", "psql", "-U", s.postgres_user, "-d", s.postgres_db, "-tA", "-c", sql,
            check=False, capture=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    # -- keys ----------------------------------------------------------------

    def ensure_wallet(self, name):
        base = self.h("wallets", name)
        cbase = self.c("wallets", name)
        if not os.path.isfile(os.path.join(base, "stake.addr")):
            os.makedirs(base, exist_ok=True)
            self.bash(" && ".join([
                _cmd("cardano-cli", "conway", "address", "key-gen",
                     "--verification-key-file", f"{cbase}/payment.vkey", "--signing-key-file", f"{cbase}/payment.skey"),
                _cmd("cardano-cli", "conway", "stake-address", "key-gen",
                     "--verification-key-file", f"{cbase}/stake.vkey", "--signing-key-file", f"{cbase}/stake.skey"),
                _cmd("cardano-cli", "conway", "address", "build",
                     "--payment-verification-key-file", f"{cbase}/payment.vkey",
                     "--stake-verification-key-file", f"{cbase}/stake.vkey",
                     "--testnet-magic", str(DEVNET_MAGIC), "--out-file", f"{cbase}/payment.addr"),
                _cmd("cardano-cli", "conway", "stake-address", "build",
                     "--stake-verification-key-file", f"{cbase}/stake.vkey",
                     "--testnet-magic", str(DEVNET_MAGIC), "--out-file", f"{cbase}/stake.addr"),
            ]))
        return {
            "name": name,
            "dir": cbase,
            "address": _read(os.path.join(base, "payment.addr")),
            "stake_address": _read(os.path.join(base, "stake.addr")),
            "payment_skey": f"{cbase}/payment.skey",
            "stake_vkey": f"{cbase}/stake.vkey",
            "stake_skey": f"{cbase}/stake.skey",
        }

    def ensure_drep(self, name):
        base = self.h("dreps", name)
        cbase = self.c("dreps", name)
        if not os.path.isfile(os.path.join(base, "drep.id")):
            os.makedirs(base, exist_ok=True)
            self.bash(" && ".join([
                _cmd("cardano-cli", "conway", "governance", "drep", "key-gen",
                     "--verification-key-file", f"{cbase}/drep.vkey", "--signing-key-file", f"{cbase}/drep.skey"),
                _cmd("cardano-cli", "conway", "governance", "drep", "id",
                     "--drep-verification-key-file", f"{cbase}/drep.vkey", "--output-hex",
                     "--out-file", f"{cbase}/drep.hash"),
                _cmd("cardano-cli", "conway", "governance", "drep", "id",
                     "--drep-verification-key-file", f"{cbase}/drep.vkey", "--output-bech32",
                     "--out-file", f"{cbase}/drep.id"),
            ]))
        return {
            "name": name,
            "vkey": f"{cbase}/drep.vkey",
            "skey": f"{cbase}/drep.skey",
            "hash": _read(os.path.join(base, "drep.hash")),
            "id": _read(os.path.join(base, "drep.id")),
        }

    def ensure_new_cc_member(self):
        base = self.h("committee-new")
        cbase = self.c("committee-new")
        if not os.path.isfile(os.path.join(base, "cc.cold.hash")):
            os.makedirs(base, exist_ok=True)
            self.bash(" && ".join([
                _cmd("cardano-cli", "conway", "governance", "committee", "key-gen-cold",
                     "--cold-verification-key-file", f"{cbase}/cc.cold.vkey",
                     "--cold-signing-key-file", f"{cbase}/cc.cold.skey"),
                _cmd("cardano-cli", "conway", "governance", "committee", "key-hash",
                     "--verification-key-file", f"{cbase}/cc.cold.vkey") + f" > {cbase}/cc.cold.hash",
            ]))
        return {"vkey": f"{cbase}/cc.cold.vkey", "hash": _read(os.path.join(base, "cc.cold.hash"))}

    def committee_members(self):
        members = []
        root = os.path.join(self.settings.dir, "keys", "committee")
        for name in sorted(os.listdir(root)):
            cbase = f"{C_ROOT}/keys/committee/{name}"
            members.append({
                "name": name,
                "cold_vkey": f"{cbase}/cc.cold.vkey",
                "cold_skey": f"{cbase}/cc.cold.skey",
                "hot_vkey": f"{cbase}/cc.hot.vkey",
                "hot_skey": f"{cbase}/cc.hot.skey",
            })
        return members

    # -- anchors -------------------------------------------------------------

    def anchor(self, name, document):
        data = json.dumps(document, indent=2).encode("utf-8")
        with open(os.path.join(self.anchor_dir, name), "wb") as file:
            file.write(data)
        return f"{self.anchor_base}/{name}", blake2b_256(data)

    # -- transactions --------------------------------------------------------

    def utxos(self, address):
        return self.query("utxo", "--address", address, "--output-json") or {}

    def balance(self, address):
        return sum(entry["value"]["lovelace"] for entry in self.utxos(address).values())

    def submit(self, label, payer, signing_keys, outs=(), certs=(), proposals=(), votes=()):
        utxos = self.utxos(payer["address"])
        if not utxos:
            raise RuntimeError(f"{payer['name']} ({payer['address']}) has no funds")
        name = f"{int(time.time() * 1000)}-{label}"
        body, signed = self.c("tx", f"{name}.body"), self.c("tx", f"{name}.signed")
        os.makedirs(self.h("tx"), exist_ok=True)
        args = ["cardano-cli", "conway", "transaction", "build", "--testnet-magic", str(DEVNET_MAGIC)]
        for txin in utxos:
            args += ["--tx-in", txin]
        for out in outs:
            args += ["--tx-out", out]
        for cert in certs:
            args += ["--certificate-file", cert]
        for proposal in proposals:
            args += ["--proposal-file", proposal]
        for vote in votes:
            args += ["--vote-file", vote]
        args += ["--change-address", payer["address"], "--witness-override", str(len(signing_keys)), "--out-file", body]
        sign = ["cardano-cli", "conway", "transaction", "sign", "--tx-body-file", body, "--out-file", signed,
                "--testnet-magic", str(DEVNET_MAGIC)]
        for key in signing_keys:
            sign += ["--signing-key-file", key]
        output = self.bash(" && ".join([
            _cmd(*args) + " >/dev/null",
            _cmd(*sign),
            _cmd("cardano-cli", "conway", "transaction", "txid", "--tx-file", signed, "--output-text"),
            _cmd("cardano-cli", "conway", "transaction", "submit", "--tx-file", signed,
                 "--testnet-magic", str(DEVNET_MAGIC)) + " >/dev/null",
        ]))
        submitted = time.time()
        tx_id = output.splitlines()[-1].strip()
        self.wait_tx(tx_id)
        confirmed = time.time() - submitted
        log(f"  {label}: {tx_id} (confirmed in {confirmed:.1f}s)")
        self.timings.setdefault("tx_confirmation_seconds", []).append(round(confirmed, 2))
        return tx_id, submitted

    def wait_tx(self, tx_id, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.query("utxo", "--tx-in", f"{tx_id}#0", "--output-json"):
                return
            time.sleep(0.3)
        raise RuntimeError(f"transaction {tx_id} was not confirmed within {timeout}s")

    def fund(self, faucet, wallets):
        outs = []
        for wallet in wallets:
            target = WALLET_FUNDS_ADA[wallet["name"]] * ADA
            if self.balance(wallet["address"]) < target // 2:
                outs.append(f"{wallet['address']}+{target}")
        if outs:
            self.submit("fund-wallets", faucet, [faucet["payment_skey"]], outs=outs)

    # -- certificates ----------------------------------------------------------

    def cert(self, name, *args):
        path = self.c("certs", f"{name}.cert")
        os.makedirs(self.h("certs"), exist_ok=True)
        self.cli(*args, "--out-file", path)
        return path

    def stake_registered(self, wallet):
        return bool(self.query("stake-address-info", "--address", wallet["stake_address"]))

    def drep_registered(self, drep):
        return bool(self.query("drep-state", "--drep-key-hash", drep["hash"]))

    def drep_document(self, name, given_name, objectives):
        return {
            "@context": CIP119_CONTEXT,
            "hashAlgorithm": "blake2b-256",
            "body": {
                "givenName": given_name,
                "objectives": objectives,
                "motivations": "Exercise governance tooling on the adaup devnet.",
                "qualifications": "Generated by the adaup smoke test.",
                "references": [],
            },
            "authors": [],
        }

    def proposal_document(self, title, abstract):
        return {
            "@context": CIP108_CONTEXT,
            "hashAlgorithm": "blake2b-256",
            "body": {
                "title": title,
                "abstract": abstract,
                "motivation": "Seeded by `cardano devnet smoke` to exercise governance tooling.",
                "rationale": "Devnet test data.",
                "references": [],
            },
            "authors": [],
        }

    # -- governance state --------------------------------------------------------

    def gov_state(self):
        return self.query("gov-state")

    def prev_action(self, action, gov_state):
        purpose = PREV_PURPOSE.get(action)
        if not purpose:
            return []
        prev = gov_state["nextRatifyState"]["nextEnactState"]["prevGovActionIds"].get(purpose)
        if not prev:
            return []
        return ["--prev-governance-action-tx-id", prev["txId"], "--prev-governance-action-index", str(prev["govActionIx"])]

    def wait_dbsync_tx(self, tx_id, since, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            found = self.psql(
                "select count(*) from gov_action_proposal g join tx on tx.id = g.tx_id "
                f"where tx.hash = '\\x{tx_id}'"
            )
            if found and found != "0":
                return round(time.time() - since, 1)
            time.sleep(0.2)
        return None

    def committee_state(self):
        return self.query("committee-state")


def _cmd(*args):
    return " ".join(shlex.quote(str(arg)) for arg in args)


def _read(path):
    with open(path, "r", encoding="utf-8") as file:
        return file.read().strip()


def _parse_list(value, default, allowed):
    if value is None:
        items = list(default)
    else:
        items = [item.strip() for item in value.split(",") if item.strip()]
    if items == ["all"]:
        items = list(allowed)
    if items == ["none"]:
        items = []
    unknown = [item for item in items if item not in allowed]
    if unknown:
        raise RuntimeError(f"unknown governance action(s): {', '.join(unknown)} (known: {', '.join(allowed)})")
    return items


def run_smoke(settings, actions=None, ratify=None, wait_enactment=True):
    require_docker()
    actions = _parse_list(actions or os.environ.get("ADAUP_DEVNET_SMOKE_ACTIONS"), ALL_ACTIONS, ALL_ACTIONS)
    ratify = _parse_list(ratify or os.environ.get("ADAUP_DEVNET_SMOKE_RATIFY"), DEFAULT_RATIFY, ALL_ACTIONS)
    smoke = Smoke(settings)
    started = time.time()

    tip = smoke.tip()
    if not tip:
        raise RuntimeError("the docker devnet is not running (start it with `cardano devnet up --docker -d`)")
    log(f"Devnet tip: block {tip['block']}, epoch {tip['epoch']}")
    pp = smoke.pparams()
    key_deposit = pp["stakeAddressDeposit"]
    drep_deposit = pp["dRepDeposit"]
    action_deposit = pp["govActionDeposit"]

    keys_root = f"{C_ROOT}/keys"
    faucet = {
        "name": "faucet",
        "address": _read(os.path.join(settings.dir, "keys", "faucet", "payment.addr")),
        "payment_skey": f"{keys_root}/faucet/payment.skey",
    }
    pool_cold_vkey = f"{keys_root}/pool/cold.vkey"
    pool_cold_skey = f"{keys_root}/pool/cold.skey"

    log("Preparing keys...")
    wallets = {name: smoke.ensure_wallet(name) for name in WALLET_FUNDS_ADA}
    proposer = wallets["proposer"]
    drep1 = smoke.ensure_drep("drep1")
    drep2 = smoke.ensure_drep("drep2")
    committee = smoke.committee_members()

    log("Funding wallets from the faucet...")
    smoke.fund(faucet, list(wallets.values()))

    log("Stake registration...")
    certs, signers = [], []
    for wallet in wallets.values():
        if not smoke.stake_registered(wallet):
            certs.append(smoke.cert(
                f"{wallet['name']}-stake-reg", "conway", "stake-address", "registration-certificate",
                "--stake-verification-key-file", wallet["stake_vkey"], "--key-reg-deposit-amt", str(key_deposit),
            ))
            signers.append(wallet["stake_skey"])
    if certs:
        smoke.submit("stake-registration", proposer, [proposer["payment_skey"], *signers], certs=certs)
    else:
        log("  already registered")

    log("DRep registration...")
    for drep, given_name in ((drep1, "adaup devnet DRep 1"), (drep2, "adaup devnet DRep 2")):
        if smoke.drep_registered(drep):
            log(f"  {drep['name']} already registered")
            continue
        url, data_hash = smoke.anchor(f"{drep['name']}.jsonld", smoke.drep_document(drep["name"], given_name, "Initial registration."))
        cert = smoke.cert(
            f"{drep['name']}-reg", "conway", "governance", "drep", "registration-certificate",
            "--drep-verification-key-file", drep["vkey"], "--key-reg-deposit-amt", str(drep_deposit),
            "--drep-metadata-url", url, "--drep-metadata-hash", data_hash,
        )
        smoke.submit(f"{drep['name']}-registration", proposer, [proposer["payment_skey"], drep["skey"]], certs=[cert])

    log("DRep update...")
    url, data_hash = smoke.anchor(
        f"drep1-update-{int(time.time())}.jsonld",
        smoke.drep_document("drep1", "adaup devnet DRep 1", f"Updated at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}."),
    )
    cert = smoke.cert(
        "drep1-update", "conway", "governance", "drep", "update-certificate",
        "--drep-verification-key-file", drep1["vkey"], "--drep-metadata-url", url, "--drep-metadata-hash", data_hash,
    )
    smoke.submit("drep1-update", proposer, [proposer["payment_skey"], drep1["skey"]], certs=[cert])

    log("Vote delegation...")
    delegations = (
        (wallets["proposer"], ["--drep-verification-key-file", drep1["vkey"]]),
        (wallets["abstainer"], ["--always-abstain"]),
        (wallets["no-confidence"], ["--always-no-confidence"]),
        (wallets["retiring"], ["--drep-verification-key-file", drep2["vkey"]]),
    )
    certs = [
        smoke.cert(f"{wallet['name']}-vote-deleg", "conway", "stake-address", "vote-delegation-certificate",
                   "--stake-verification-key-file", wallet["stake_vkey"], *target)
        for wallet, target in delegations
    ]
    smoke.submit("vote-delegation", proposer,
                 [proposer["payment_skey"], *[wallet["stake_skey"] for wallet, _ in delegations]], certs=certs)

    log("DRep retirement (drep2)...")
    cert = smoke.cert(
        "drep2-retire", "conway", "governance", "drep", "retirement-certificate",
        "--drep-verification-key-file", drep2["vkey"], "--deposit-amt", str(drep_deposit),
    )
    smoke.submit("drep2-retirement", proposer, [proposer["payment_skey"], drep2["skey"]], certs=[cert])

    log("Constitutional committee hot key authorisation...")
    authorised = _authorised_hot_keys(smoke.committee_state())
    certs, signers = [], []
    for member in committee:
        cold_hash = smoke.cli("conway", "governance", "committee", "key-hash", "--verification-key-file", member["cold_vkey"])
        hot_hash = smoke.cli("conway", "governance", "committee", "key-hash", "--verification-key-file", member["hot_vkey"])
        if authorised.get(cold_hash) == hot_hash:
            continue
        certs.append(smoke.cert(
            f"{member['name']}-hot-auth", "conway", "governance", "committee",
            "create-hot-key-authorization-certificate",
            "--cold-verification-key-file", member["cold_vkey"], "--hot-verification-key-file", member["hot_vkey"],
        ))
        signers.append(member["cold_skey"])
    if certs:
        smoke.submit("cc-hot-key-authorisation", proposer, [proposer["payment_skey"], *signers], certs=certs)
    else:
        log("  already authorised")

    log(f"Proposals: {', '.join(actions) or 'none'}")
    gov_state = smoke.gov_state()
    epoch = smoke.tip()["epoch"]
    common = [
        "--testnet", "--governance-action-deposit", str(action_deposit),
        "--deposit-return-stake-verification-key-file", proposer["stake_vkey"],
    ]
    proposals = []
    run_id = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    os.makedirs(smoke.h("proposals"), exist_ok=True)
    for action in actions:
        url, data_hash = smoke.anchor(
            f"proposal-{action}-{run_id}.jsonld",
            smoke.proposal_document(f"Devnet {action} proposal {run_id}", f"A {action} governance action created by the adaup smoke test."),
        )
        out = smoke.c("proposals", f"{action}-{run_id}.action")
        base = [*common, "--anchor-url", url, "--anchor-data-hash", data_hash, "--out-file", out]
        prev = smoke.prev_action(action, gov_state)
        if action == "info":
            smoke.cli("conway", "governance", "action", "create-info", *base)
        elif action == "treasury":
            smoke.cli("conway", "governance", "action", "create-treasury-withdrawal", *base,
                      "--funds-receiving-stake-verification-key-file", proposer["stake_vkey"],
                      "--transfer", str(TREASURY_WITHDRAWAL_ADA * ADA))
        elif action == "parameter":
            current = float(pp.get("treasuryCut", 0.2))
            new_value = "1/4" if abs(current - 0.25) > 1e-9 else "1/5"
            smoke.cli("conway", "governance", "action", "create-protocol-parameters-update", *base, *prev,
                      "--treasury-expansion", new_value)
        elif action == "hardfork":
            major = pp["protocolVersion"]["major"] + 1
            smoke.cli("conway", "governance", "action", "create-hardfork", *base, *prev,
                      "--protocol-major-version", str(major), "--protocol-minor-version", "0")
        elif action == "no-confidence":
            smoke.cli("conway", "governance", "action", "create-no-confidence", *base, *prev)
        elif action == "committee":
            new_member = smoke.ensure_new_cc_member()
            smoke.cli("conway", "governance", "action", "update-committee", *base, *prev,
                      "--add-cc-cold-verification-key-file", new_member["vkey"],
                      "--epoch", str(epoch + min(100, pp["committeeMaxTermLength"])),
                      "--threshold", settings.committee_threshold)
        elif action == "constitution":
            c_url, c_hash = smoke.anchor(
                f"constitution-{run_id}.jsonld",
                {"@context": CIP100_CONTEXT, "hashAlgorithm": "blake2b-256",
                 "body": {"title": f"Devnet constitution {run_id}", "abstract": "No guardrail script."}, "authors": []},
            )
            smoke.cli("conway", "governance", "action", "create-constitution", *base, *prev,
                      "--constitution-url", c_url, "--constitution-hash", c_hash)
        tx_id, submitted = smoke.submit(f"proposal-{action}", proposer, [proposer["payment_skey"]], proposals=[out])
        tip = smoke.tip()
        proposals.append({"action": action, "txId": tx_id, "index": 0, "submitted": submitted,
                          "epoch": tip["epoch"], "slotInEpoch": tip["slotInEpoch"],
                          "anchor": url, "ratify": action in ratify or action == "info"})
        if settings.dbsync and len(proposals) == 1:
            latency = smoke.wait_dbsync_tx(tx_id, submitted)
            smoke.timings["dbsync_proposal_latency_seconds"] = latency
            log(f"    visible in db-sync gov_action_proposal {latency}s after submission")

    if proposals:
        log("Voting...")
        for role in ("drep", "spo", "cc"):
            vote_files, signers = [], []
            for proposal in proposals:
                if role not in ELIGIBLE_VOTERS[proposal["action"]]:
                    continue
                choice = "--yes" if proposal["ratify"] else "--no"
                voters = {
                    "drep": [("drep1", ["--drep-verification-key-file", drep1["vkey"]], drep1["skey"])],
                    "spo": [("pool", ["--cold-verification-key-file", pool_cold_vkey], pool_cold_skey)],
                    "cc": [(m["name"], ["--cc-hot-verification-key-file", m["hot_vkey"]], m["hot_skey"]) for m in committee],
                }[role]
                for voter_name, voter_args, skey in voters:
                    v_url, v_hash = smoke.anchor(
                        f"vote-{voter_name}-{proposal['txId'][:16]}.jsonld",
                        {"@context": CIP100_CONTEXT, "hashAlgorithm": "blake2b-256",
                         "body": {"comment": f"{voter_name} votes {choice[2:]} on {proposal['action']}"}, "authors": []},
                    )
                    vote_file = smoke.c("votes", f"{voter_name}-{proposal['txId'][:16]}.vote")
                    os.makedirs(smoke.h("votes"), exist_ok=True)
                    smoke.cli("conway", "governance", "vote", "create", choice,
                              "--governance-action-tx-id", proposal["txId"], "--governance-action-index", "0",
                              *voter_args, "--anchor-url", v_url, "--anchor-data-hash", v_hash, "--out-file", vote_file)
                    vote_files.append(vote_file)
                    if skey not in signers:
                        signers.append(skey)
            if vote_files:
                smoke.submit(f"{role}-votes", proposer, [proposer["payment_skey"], *signers], votes=vote_files)

    result = {
        "startedAt": started,
        "epochAtProposal": epoch,
        "wallets": {name: {"address": w["address"], "stakeAddress": w["stake_address"], "dir": w["dir"]} for name, w in wallets.items()},
        "dreps": {d["name"]: {"id": d["id"], "hash": d["hash"]} for d in (drep1, drep2)},
        "proposals": proposals,
        "timings": smoke.timings,
    }
    _write_result(smoke, result)

    if settings.dbsync:
        _check_dbsync(smoke, proposals, result)
    if wait_enactment and proposals:
        _wait_enactment(smoke, proposals, result)

    result["timings"]["total_seconds"] = round(time.time() - started, 1)
    _write_result(smoke, result)
    log(f"\nSmoke test finished in {result['timings']['total_seconds']}s; summary in {smoke.h('result.json')}")
    return result


def _write_result(smoke, result):
    with open(smoke.h("result.json"), "w", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
        file.write("\n")


def _authorised_hot_keys(committee_state):
    authorised = {}
    for cold, member in (committee_state or {}).get("committee", {}).items():
        status = member.get("hotCredsAuthStatus", {})
        if status.get("tag") == "MemberAuthorized":
            cred = status.get("contents", {})
            authorised[cold.split("-", 1)[-1]] = cred.get("keyHash") or cred.get("scriptHash")
    return authorised


def _check_dbsync(smoke, proposals, result):
    log("Checking db-sync...")
    for proposal in proposals:
        if smoke.wait_dbsync_tx(proposal["txId"], proposal["submitted"]) is None:
            log(f"  {proposal['action']} proposal is missing from db-sync")
    counts = {}
    for table in ("drep_registration", "delegation_vote", "gov_action_proposal", "voting_procedure",
                  "committee_registration", "drep_distr", "voting_anchor", "off_chain_vote_data",
                  "off_chain_vote_gov_action_data", "off_chain_vote_drep_data", "off_chain_vote_fetch_error"):
        counts[table] = smoke.psql(f"select count(*) from {table}")
    result["dbsyncCounts"] = counts
    log("  " + ", ".join(f"{table}={count}" for table, count in counts.items()))


def _wait_enactment(smoke, proposals, result):
    targets = [p for p in proposals if p["ratify"] and p["action"] != "info"]
    if not targets:
        return
    epoch_seconds = smoke.settings.epoch_seconds
    timeout = max(300, epoch_seconds * 6)
    log(f"Waiting for enactment of {', '.join(p['action'] for p in targets)} (up to {timeout:.0f}s)...")
    deadline = time.time() + timeout
    pending = {p["txId"]: p for p in targets}
    while pending and time.time() < deadline:
        state = smoke.gov_state()
        live = {(p["actionId"]["txId"], p["actionId"]["govActionIx"]) for p in state["proposals"]}
        enacted = state["nextRatifyState"]["nextEnactState"]["prevGovActionIds"]
        enacted_ids = {v["txId"] for v in enacted.values() if v}
        tip = smoke.tip()
        for tx_id, proposal in list(pending.items()):
            if (tx_id, 0) in live:
                continue
            if proposal["action"] == "treasury" or tx_id in enacted_ids:
                proposal["enactedSeconds"] = round(time.time() - proposal["submitted"], 1)
                proposal["enactedEpoch"] = tip["epoch"]
                del pending[tx_id]
                log(f"  {proposal['action']} enacted in epoch {tip['epoch']} "
                    f"({proposal['enactedSeconds']}s after submission)")
            else:
                proposal["expired"] = True
                del pending[tx_id]
                log(f"  {proposal['action']} left the ledger without being enacted")
        time.sleep(2)
    for proposal in pending.values():
        log(f"  {proposal['action']} not enacted within {timeout:.0f}s")
    if smoke.settings.dbsync:
        time.sleep(max(3.0, smoke.settings.slot_length * 20))
        rows = smoke.psql(
            "select encode(tx.hash, 'hex'), g.type, g.ratified_epoch, g.enacted_epoch, g.expired_epoch "
            "from gov_action_proposal g join tx on tx.id = g.tx_id order by g.id"
        ) or ""
        by_tx = {}
        for line in rows.splitlines():
            tx_hash, kind, ratified, enacted, expired = line.split("|")
            by_tx[tx_hash] = {"type": kind, "ratifiedEpoch": ratified or None,
                              "enactedEpoch": enacted or None, "expiredEpoch": expired or None}
        for proposal in proposals:
            proposal["dbsync"] = by_tx.get(proposal["txId"])
        log("  db-sync gov_action_proposal: " + ", ".join(
            f"{p['action']}={(p.get('dbsync') or {}).get('enactedEpoch') or '-'}" for p in proposals))


CIP100_CONTEXT = {
    "@language": "en-us",
    "CIP100": "https://github.com/cardano-foundation/CIPs/blob/master/CIP-0100/README.md#",
    "hashAlgorithm": "CIP100:hashAlgorithm",
    "body": {"@id": "CIP100:body", "@context": {"comment": "CIP100:comment"}},
    "authors": {"@id": "CIP100:authors", "@container": "@set"},
}

CIP108_CONTEXT = {
    "@language": "en-us",
    "CIP100": "https://github.com/cardano-foundation/CIPs/blob/master/CIP-0100/README.md#",
    "CIP108": "https://github.com/cardano-foundation/CIPs/blob/master/CIP-0108/README.md#",
    "hashAlgorithm": "CIP100:hashAlgorithm",
    "body": {
        "@id": "CIP108:body",
        "@context": {
            "references": {
                "@id": "CIP108:references",
                "@container": "@set",
                "@context": {"label": "CIP100:reference-label", "uri": "CIP100:reference-uri"},
            },
            "title": "CIP108:title",
            "abstract": "CIP108:abstract",
            "motivation": "CIP108:motivation",
            "rationale": "CIP108:rationale",
        },
    },
    "authors": {"@id": "CIP100:authors", "@container": "@set"},
}

CIP119_CONTEXT = {
    "@language": "en-us",
    "CIP100": "https://github.com/cardano-foundation/CIPs/blob/master/CIP-0100/README.md#",
    "CIP119": "https://github.com/cardano-foundation/CIPs/blob/master/CIP-0119/README.md#",
    "hashAlgorithm": "CIP100:hashAlgorithm",
    "body": {
        "@id": "CIP119:body",
        "@context": {
            "references": {"@id": "CIP119:references", "@container": "@set"},
            "givenName": "CIP119:givenName",
            "objectives": "CIP119:objectives",
            "motivations": "CIP119:motivations",
            "qualifications": "CIP119:qualifications",
        },
    },
    "authors": {"@id": "CIP100:authors", "@container": "@set"},
}
