package com.example.lazypc.ui.components

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp


@Composable
fun BottomToolbar(

    keyboardVisible: Boolean,

    dragModeEnabled: Boolean,

    onToggleKeyboard: () -> Unit,

    onToggleDrag: () -> Unit

) {

    Surface(

        modifier = Modifier
            .fillMaxWidth()
            .height(44.dp),

        color = Color(0xFF121212),

        tonalElevation = 4.dp

    ) {

        Row(

            modifier = Modifier
                .fillMaxSize()
                .padding(
                    horizontal = 8.dp,
                    vertical = 4.dp
                ),

            horizontalArrangement =
                Arrangement.spacedBy(8.dp),

            verticalAlignment =
                Alignment.CenterVertically

        ) {

            Button(

                modifier =
                    Modifier.height(36.dp),

                onClick =
                    onToggleKeyboard,

                contentPadding =
                    PaddingValues(
                        horizontal = 14.dp,
                        vertical = 0.dp
                    ),

                colors =
                    ButtonDefaults.buttonColors(

                        containerColor =
                            Color(0xFF2C2C2C)
                    )

            ) {

                Text(

                    text =
                        if (keyboardVisible)

                            "⌨ KB OFF"

                        else

                            "⌨ KB ON",

                    color =
                        Color.White,

                    fontSize =
                        14.sp
                )
            }


            Button(

                modifier =
                    Modifier.height(36.dp),

                onClick =
                    onToggleDrag,

                contentPadding =
                    PaddingValues(
                        horizontal = 14.dp,
                        vertical = 0.dp
                    ),

                colors =
                    ButtonDefaults.buttonColors(

                        containerColor =

                            if (dragModeEnabled)

                                Color(0xFF2E7D32)

                            else

                                Color(0xFF2C2C2C)
                    )

            ) {

                Text(

                    text =
                        if (dragModeEnabled)

                            "🧲 DRAG ON"

                        else

                            "🧲 DRAG OFF",

                    color =
                        Color.White,

                    fontSize =
                        14.sp
                )
            }
        }
    }
}