use jni::objects::{JByteArray, JClass};
use jni::sys::{jboolean, jbyteArray, jlong, JNI_FALSE, JNI_TRUE};
use jni::JNIEnv;
use snow::{params::NoiseParams, Builder, HandshakeState, TransportState};
use std::panic::{catch_unwind, AssertUnwindSafe};

const PROLOGUE: &[u8] = b"lazypc/v4";
const PAIRING_PATTERN: &str = "Noise_IKpsk2_25519_ChaChaPoly_SHA256";
const SESSION_PATTERN: &str = "Noise_IK_25519_ChaChaPoly_SHA256";
const MAX_MESSAGE: usize = 64 * 1024;

// The JNI handle is owned by exactly one Kotlin SecureLinkNoiseSession.
enum State {
    Handshake(HandshakeState),
    Transport(TransportState),
    Dead,
}

struct NoiseSession {
    state: State,
    handshake_hash: Option<Vec<u8>>,
}

impl NoiseSession {
    fn initiator(local_private: &[u8], remote_public: &[u8], psk: Option<&[u8]>) -> Result<Self, String> {
        validate_key(local_private, "local private key")?;
        validate_key(remote_public, "remote public key")?;
        let pattern = if psk.is_some() { PAIRING_PATTERN } else { SESSION_PATTERN };
        let params: NoiseParams = pattern.parse().map_err(|e| format!("invalid Noise pattern: {e}"))?;
        let mut builder = Builder::new(params)
            .local_private_key(local_private).map_err(err)?
            .remote_public_key(remote_public).map_err(err)?
            .prologue(PROLOGUE).map_err(err)?;
        if let Some(key) = psk {
            validate_key(key, "pairing PSK")?;

            let key: &[u8; 32] = key
                .try_into()
                .map_err(|_| "pairing PSK must be exactly 32 bytes")?;

            builder = builder.psk(2, key).map_err(err)?;
        }
        let state = builder.build_initiator().map_err(err)?;
        Ok(Self { state: State::Handshake(state), handshake_hash: None })
    }

    #[cfg(test)]
    fn responder(local_private: &[u8], psk: Option<&[u8]>) -> Result<Self, String> {
        validate_key(local_private, "local private key")?;
        let pattern = if psk.is_some() { PAIRING_PATTERN } else { SESSION_PATTERN };
        let params: NoiseParams = pattern.parse().map_err(|e| format!("invalid Noise pattern: {e}"))?;
        let mut builder = Builder::new(params)
            .local_private_key(local_private).map_err(err)?
            .prologue(PROLOGUE).map_err(err)?;
        if let Some(key) = psk {
            validate_key(key, "pairing PSK")?;

            let key: &[u8; 32] = key
                .try_into()
                .map_err(|_| "pairing PSK must be exactly 32 bytes")?;

            builder = builder.psk(2, key).map_err(err)?;
        }
        let state = builder.build_responder().map_err(err)?;
        Ok(Self { state: State::Handshake(state), handshake_hash: None })
    }

    fn write_message(&mut self, payload: &[u8]) -> Result<Vec<u8>, String> {
        if payload.len() > MAX_MESSAGE { return Err("Noise payload exceeds 64 KiB".into()); }
        let state = std::mem::replace(&mut self.state, State::Dead);
        let mut output = vec![0u8; MAX_MESSAGE + 1024];
        match state {
            State::Handshake(mut hs) => {
                let len = match hs.write_message(payload, &mut output) {
                    Ok(n) => n,
                    Err(e) => return Err(err(e)),
                };
                output.truncate(len);
                if hs.is_handshake_finished() {
                    self.handshake_hash = Some(hs.get_handshake_hash().to_vec());
                    self.state = State::Transport(hs.into_transport_mode().map_err(err)?);
                } else {
                    self.state = State::Handshake(hs);
                }
                Ok(output)
            }
            State::Transport(mut transport) => {
                let len = match transport.write_message(payload, &mut output) {
                    Ok(n) => n,
                    Err(e) => return Err(err(e)),
                };
                output.truncate(len);
                self.state = State::Transport(transport);
                Ok(output)
            }
            State::Dead => Err("Noise session is closed".into()),
        }
    }

    fn read_message(&mut self, message: &[u8]) -> Result<Vec<u8>, String> {
        if message.is_empty() || message.len() > MAX_MESSAGE { return Err("Invalid Noise message size".into()); }
        let state = std::mem::replace(&mut self.state, State::Dead);
        let mut output = vec![0u8; MAX_MESSAGE + 1024];
        match state {
            State::Handshake(mut hs) => {
                let len = match hs.read_message(message, &mut output) {
                    Ok(n) => n,
                    Err(e) => return Err(err(e)),
                };
                output.truncate(len);
                if hs.is_handshake_finished() {
                    self.handshake_hash = Some(hs.get_handshake_hash().to_vec());
                    self.state = State::Transport(hs.into_transport_mode().map_err(err)?);
                } else {
                    self.state = State::Handshake(hs);
                }
                Ok(output)
            }
            State::Transport(mut transport) => {
                let len = match transport.read_message(message, &mut output) {
                    Ok(n) => n,
                    Err(e) => return Err(err(e)),
                };
                output.truncate(len);
                self.state = State::Transport(transport);
                Ok(output)
            }
            State::Dead => Err("Noise session is closed".into()),
        }
    }

    fn hash(&self) -> Result<&[u8], String> {
        self.handshake_hash.as_deref().ok_or_else(|| "Noise handshake is not complete".into())
    }

    fn is_finished(&self) -> bool { matches!(&self.state, State::Transport(_)) }
}

fn validate_key(key: &[u8], name: &str) -> Result<(), String> {
    if key.len() != 32 { return Err(format!("{name} must be exactly 32 bytes")); }
    if name.contains("public") && key.iter().all(|b| *b == 0) {
        return Err(format!("{name} must not be all zeroes"));
    }
    Ok(())
}
fn err<E: std::fmt::Display>(e: E) -> String { e.to_string() }
fn throw(env: &mut JNIEnv, message: &str) {
    let _ = env.throw_new("java/lang/IllegalStateException", message);
}
fn bytes(env: &mut JNIEnv, array: JByteArray) -> Result<Vec<u8>, String> {
    env.convert_byte_array(&array).map_err(err)
}
fn java_bytes(env: &mut JNIEnv, value: &[u8]) -> jbyteArray {
    match env.byte_array_from_slice(value) {
        Ok(array) => array.into_raw(),
        Err(e) => { throw(env, &e.to_string()); std::ptr::null_mut() }
    }
}
unsafe fn session_mut<'a>(handle: jlong) -> Result<&'a mut NoiseSession, String> {
    if handle == 0 { return Err("Invalid Noise session handle".into()); }
    Ok(&mut *(handle as *mut NoiseSession))
}

#[no_mangle]
pub extern "system" fn Java_com_example_lazypc_security_SecureLinkNoiseNative_nativeGenerateStaticKeyPair(
    mut env: JNIEnv<'_>, _this: JClass<'_>,
) -> jbyteArray {
    let result = catch_unwind(AssertUnwindSafe(|| -> Result<Vec<u8>, String> {
        let params: NoiseParams = SESSION_PATTERN.parse().map_err(err)?;
        let keypair = Builder::new(params).generate_keypair().map_err(err)?;
        validate_key(&keypair.private, "generated private key")?;
        validate_key(&keypair.public, "generated public key")?;
        let mut output = Vec::with_capacity(64);
        output.extend_from_slice(&keypair.private);
        output.extend_from_slice(&keypair.public);
        Ok(output)
    }));
    match result {
        Ok(Ok(value)) => java_bytes(&mut env, &value),
        Ok(Err(e)) => { throw(&mut env, &e); std::ptr::null_mut() },
        Err(_) => { throw(&mut env, "Rust Noise key generation panicked"); std::ptr::null_mut() }
    }
}

#[no_mangle]
pub extern "system" fn Java_com_example_lazypc_security_SecureLinkNoiseNative_nativeCreateInitiator(
    mut env: JNIEnv<'_>, _this: JClass<'_>, local_private: JByteArray, remote_public: JByteArray, psk_array: JByteArray,
) -> jlong {
    let result = catch_unwind(AssertUnwindSafe(|| -> Result<NoiseSession, String> {
        let private = bytes(&mut env, local_private)?;
        let remote = bytes(&mut env, remote_public)?;
        let psk = bytes(&mut env, psk_array)?;
        let psk_ref = if psk.is_empty() { None } else { Some(psk.as_slice()) };
        NoiseSession::initiator(&private, &remote, psk_ref)
    }));
    match result {
        Ok(Ok(session)) => Box::into_raw(Box::new(session)) as jlong,
        Ok(Err(e)) => { throw(&mut env, &e); 0 },
        Err(_) => { throw(&mut env, "Rust Noise session creation panicked"); 0 }
    }
}

#[no_mangle]
pub extern "system" fn Java_com_example_lazypc_security_SecureLinkNoiseNative_nativeWriteMessage(
    mut env: JNIEnv<'_>, _this: JClass<'_>, handle: jlong, payload: JByteArray,
) -> jbyteArray {
    let result = catch_unwind(AssertUnwindSafe(|| -> Result<Vec<u8>, String> {
        let payload = bytes(&mut env, payload)?;
        unsafe { session_mut(handle)?.write_message(&payload) }
    }));
    match result {
        Ok(Ok(value)) => java_bytes(&mut env, &value),
        Ok(Err(e)) => { throw(&mut env, &e); std::ptr::null_mut() },
        Err(_) => { throw(&mut env, "Rust Noise write panicked"); std::ptr::null_mut() }
    }
}

#[no_mangle]
pub extern "system" fn Java_com_example_lazypc_security_SecureLinkNoiseNative_nativeReadMessage(
    mut env: JNIEnv<'_>, _this: JClass<'_>, handle: jlong, message: JByteArray,
) -> jbyteArray {
    let result = catch_unwind(AssertUnwindSafe(|| -> Result<Vec<u8>, String> {
        let message = bytes(&mut env, message)?;
        unsafe { session_mut(handle)?.read_message(&message) }
    }));
    match result {
        Ok(Ok(value)) => java_bytes(&mut env, &value),
        Ok(Err(e)) => { throw(&mut env, &e); std::ptr::null_mut() },
        Err(_) => { throw(&mut env, "Rust Noise read panicked"); std::ptr::null_mut() }
    }
}

#[no_mangle]
pub extern "system" fn Java_com_example_lazypc_security_SecureLinkNoiseNative_nativeHandshakeHash(
    mut env: JNIEnv<'_>, _this: JClass<'_>, handle: jlong,
) -> jbyteArray {
    let result = catch_unwind(AssertUnwindSafe(|| -> Result<Vec<u8>, String> {
        unsafe { Ok(session_mut(handle)?.hash()?.to_vec()) }
    }));
    match result {
        Ok(Ok(value)) => java_bytes(&mut env, &value),
        Ok(Err(e)) => { throw(&mut env, &e); std::ptr::null_mut() },
        Err(_) => { throw(&mut env, "Rust Noise hash read panicked"); std::ptr::null_mut() }
    }
}

#[no_mangle]
pub extern "system" fn Java_com_example_lazypc_security_SecureLinkNoiseNative_nativeIsHandshakeFinished(
    mut env: JNIEnv<'_>, _this: JClass<'_>, handle: jlong,
) -> jboolean {
    let result = catch_unwind(AssertUnwindSafe(|| -> Result<bool, String> {
        unsafe { Ok(session_mut(handle)?.is_finished()) }
    }));
    match result {
        Ok(Ok(true)) => JNI_TRUE,
        Ok(Ok(false)) => JNI_FALSE,
        Ok(Err(e)) => { throw(&mut env, &e); JNI_FALSE },
        Err(_) => { throw(&mut env, "Rust Noise state check panicked"); JNI_FALSE }
    }
}

#[no_mangle]
pub extern "system" fn Java_com_example_lazypc_security_SecureLinkNoiseNative_nativeDestroy(
    _env: JNIEnv<'_>, _this: JClass<'_>, handle: jlong,
) {
    if handle != 0 { unsafe { drop(Box::from_raw(handle as *mut NoiseSession)); } }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn keypair() -> snow::Keypair {
        let params: NoiseParams = SESSION_PATTERN.parse().unwrap();
        Builder::new(params).generate_keypair().unwrap()
    }

    #[test]
    fn pairing_ikpsk2_finishes_and_transports_both_directions() {
        let pc = keypair();
        let phone = keypair();
        let psk = [0x5a; 32];
        let mut phone_noise = NoiseSession::initiator(&phone.private, &pc.public, Some(&psk)).unwrap();
        let mut pc_noise = NoiseSession::responder(&pc.private, Some(&psk)).unwrap();

        let msg1 = phone_noise.write_message(b"").unwrap();
        assert!(pc_noise.read_message(&msg1).unwrap().is_empty());
        let msg2 = pc_noise.write_message(br#"{"v":4}"#).unwrap();
        assert_eq!(phone_noise.read_message(&msg2).unwrap(), br#"{"v":4}"#);
        assert!(phone_noise.is_finished());
        assert!(pc_noise.is_finished());
        assert_eq!(phone_noise.hash().unwrap(), pc_noise.hash().unwrap());

        let pair3 = phone_noise.write_message(br#"{"registration":true}"#).unwrap();
        assert_eq!(pc_noise.read_message(&pair3).unwrap(), br#"{"registration":true}"#);
        let pair4 = pc_noise.write_message(br#"{"status":"PAIRED"}"#).unwrap();
        assert_eq!(phone_noise.read_message(&pair4).unwrap(), br#"{"status":"PAIRED"}"#);
    }

    #[test]
    fn wrong_psk_fails_handshake() {
        let pc = keypair();
        let phone = keypair();
        let mut phone_noise = NoiseSession::initiator(&phone.private, &pc.public, Some(&[1; 32])).unwrap();
        let mut pc_noise = NoiseSession::responder(&pc.private, Some(&[2; 32])).unwrap();
        let msg1 = phone_noise.write_message(b"").unwrap();
        assert!(pc_noise.read_message(&msg1).is_ok());
        let msg2 = pc_noise.write_message(br#"{"v":4}"#).unwrap();
        assert!(phone_noise.read_message(&msg2).is_err());
    }
}
