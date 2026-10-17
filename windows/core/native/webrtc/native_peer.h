#pragma once

#ifdef _WIN32
#define LAZYPC_API __declspec(dllexport)
#else
#define LAZYPC_API
#endif

#include <stddef.h>

extern "C" {

LAZYPC_API int lazypc_webrtc_init();
LAZYPC_API void lazypc_webrtc_shutdown();
LAZYPC_API int lazypc_webrtc_is_initialized();

LAZYPC_API int lazypc_webrtc_create_peer_connection();
LAZYPC_API void lazypc_webrtc_close_peer_connection();
LAZYPC_API int lazypc_webrtc_has_peer_connection();
// Enables desktop capture only after the application authorizes Stage 3.
LAZYPC_API int lazypc_webrtc_set_video_enabled(int enabled);
// Enables/disables Windows render-loopback audio after Stage 3 authorization.
LAZYPC_API int lazypc_webrtc_set_audio_enabled(int enabled);

LAZYPC_API int lazypc_webrtc_create_control_channel();
LAZYPC_API int lazypc_webrtc_has_control_channel();
LAZYPC_API int lazypc_webrtc_has_auth_channel();
LAZYPC_API int lazypc_webrtc_send_auth(
    const void* data,
    size_t size,
    int binary);
LAZYPC_API int lazypc_webrtc_auth_state();

LAZYPC_API int lazypc_webrtc_create_offer(char** out_sdp);
LAZYPC_API int lazypc_webrtc_create_answer(char** out_sdp);

LAZYPC_API int lazypc_webrtc_set_remote_description(
    const char* type,
    const char* sdp);

LAZYPC_API int lazypc_webrtc_set_local_description(
    const char* type,
    const char* sdp);

LAZYPC_API int lazypc_webrtc_add_ice_candidate(
    const char* sdp_mid,
    int sdp_mline_index,
    const char* candidate);

LAZYPC_API void lazypc_webrtc_free_string(void* ptr);

LAZYPC_API int lazypc_webrtc_send_control(
    const void* data,
    size_t size,
    int binary);

LAZYPC_API int lazypc_webrtc_control_state();

/*
 * Returns:
 *   0  = no event
 *   >0 = payload size
 *   <0 = supplied payload buffer was too small
 *
 * event_type receives a zero-terminated event name.
 * event_data receives the event payload.
 * binary receives 0/1.
 */
LAZYPC_API int lazypc_webrtc_next_event(
    char* event_type,
    size_t event_type_capacity,
    char* event_data,
    size_t event_data_capacity,
    int* binary);

}
