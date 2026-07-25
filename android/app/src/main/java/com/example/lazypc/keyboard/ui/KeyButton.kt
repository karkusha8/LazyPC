package com.example.lazypc.keyboard.ui

import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.lazypc.keyboard.core.KeyId


@Composable
fun RowScope.KeyButton(

    keyId: KeyId,

    label: String,

    weight: Float,

    backgroundColor: Color =
        Color(0xFF2A2A2A),

    onClick: (KeyId) -> Unit,

    onLongPress: (KeyId) -> Unit = {}

) {

    Box(

        modifier = Modifier

            .weight(weight)

            .fillMaxHeight()

            .padding(3.dp)

            .background(

                color = backgroundColor,

                shape = RoundedCornerShape(8.dp)

            )

            .pointerInput(keyId) {

                detectTapGestures(

                    onTap = {

                        Log.d(
                            "KB_DEBUG",
                            "CLICK: $keyId"
                        )

                        onClick(keyId)

                    },


                    onLongPress = {

                        Log.d(
                            "KB_DEBUG",
                            "LONG PRESS: $keyId"
                        )

                        onLongPress(keyId)

                    }
                )
            },


        contentAlignment = Alignment.Center

    ) {


        Text(

            text = label,

            color = Color.White,

            fontSize = 16.sp,

            fontWeight = FontWeight.Medium

        )

    }
}