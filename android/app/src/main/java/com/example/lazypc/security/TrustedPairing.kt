package com.example.lazypc.security

import android.content.Context
import android.os.Build
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject

class TrustedPairing(
    private val context: Context,
    private val keyStore: SecurityKeyStore,
) {
    companion object {
        private const val VERSION = 3
        private const val ALGORITHM = "ECDSA-P256-HW-ATTESTATION-V3"
    }

    data class Invitation(
        val pairingId: String,
        val token: String,
        val nonceB64: String,
        val pcIdentityPublic: String,
    )

    fun parseQrPayload(payload: String): Invitation {
        val parts = payload.split('|')
        require(parts.size == 5) { "Invalid LazyPC pairing QR" }
        require(parts[0] == "LAZYPC_PAIR_V2") {
            "Unsupported LazyPC pairing QR"
        }

        return Invitation(
            pairingId = parts[1],
            token = parts[2],
            nonceB64 = parts[3],
            pcIdentityPublic = parts[4],
        )
    }

    fun createPairResponse(
        invitation: Invitation,
        challenge: JSONObject,
    ): JSONObject {
        require(challenge.optString("type") == "pair_challenge")
        require(challenge.optInt("version", -1) == VERSION)
        require(challenge.optString("algorithm") == ALGORITHM)

        val pairingId = challenge.optString("pairing_id")
        val nonceB64 = challenge.optString("nonce")
        val pcIdentityPublic = challenge.optString("pc_identity_public")

        require(pairingId == invitation.pairingId) {
            "Pairing ID does not match QR"
        }
        require(nonceB64 == invitation.nonceB64) {
            "Pairing nonce does not match QR"
        }
        require(pcIdentityPublic == invitation.pcIdentityPublic) {
            "PC identity does not match QR"
        }

        val nonce = Base64.decode(nonceB64, Base64.DEFAULT)
        require(nonce.size == 32) { "Invalid pairing nonce" }

        keyStore.ensureKeys()

        // Every new QR pairing rotates only the per-PC Device Key.
        // Identity and StrongBox credentials remain unchanged.
        keyStore.rotateDeviceKeyForPc(pcIdentityPublic)

        val hardware =
            keyStore.createTrustedHardwareKeyForPairing(
                nonce,
                context
            )

        val identityPublic = keyStore.identityPublicKeyBase64()
        val devicePublic =
            keyStore.devicePublicKeyBase64(pcIdentityPublic)
        val hardwarePublic = hardware.publicKeyBase64

        val identityBindingSignature =
            keyStore.signIdentityDeviceBinding(
                pairingId = invitation.pairingId,
                nonceB64 = invitation.nonceB64,
                pcIdentityPublic = invitation.pcIdentityPublic,
                identityPublic = identityPublic,
                devicePublic = devicePublic
            )

        val deviceEnrollmentSignature =
            keyStore.signDeviceEnrollmentProof(
                pairingId = invitation.pairingId,
                nonceB64 = invitation.nonceB64,
                pcIdentityPublic = invitation.pcIdentityPublic,
                identityPublic = identityPublic,
                devicePublic = devicePublic
            )

        keyStore.saveIdentityBindingSignature(
            context,
            invitation.pcIdentityPublic,
            identityBindingSignature
        )

        val hardwareTranscript =
            (
                    "LAZYPC_HW_AUTH_V1|SESSION|" +
                            invitation.pairingId + "|" +
                            invitation.nonceB64 + "|" +
                            hardwarePublic
                    ).toByteArray(Charsets.UTF_8)

        val hardwareSignature =
            keyStore.signHardwareProof(hardwareTranscript)

        return JSONObject().apply {
            put("type", "pair_response")
            put("version", VERSION)
            put("algorithm", ALGORITHM)
            put("pairing_id", invitation.pairingId)
            put("nonce", invitation.nonceB64)
            put("pc_identity_public", invitation.pcIdentityPublic)
            put("identity_public", identityPublic)
            put("device_public", devicePublic)
            put("hardware_public", hardwarePublic)
            put("identity_binding_signature", identityBindingSignature)
            put("device_enrollment_signature", deviceEnrollmentSignature)
            put("hardware_signature", hardwareSignature)
            put("attestation_challenge", hardware.attestationChallengeBase64)
            put("attestation_chain", JSONArray(hardware.attestationChainBase64))
            put("platform", "Android")
            put("manufacturer", Build.MANUFACTURER)
            put("model", Build.MODEL)
            put("android_version", Build.VERSION.RELEASE ?: "")
        }
    }
}