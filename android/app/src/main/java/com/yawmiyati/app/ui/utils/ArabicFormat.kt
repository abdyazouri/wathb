package com.yawmiyati.app.ui.utils

private val WESTERN = charArrayOf('0', '1', '2', '3', '4', '5', '6', '7', '8', '9')
private val ARABIC  = charArrayOf('٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩')

fun String.toArabicNumerals(): String = buildString {
    for (c in this@toArabicNumerals) {
        val i = WESTERN.indexOf(c)
        append(if (i >= 0) ARABIC[i] else c)
    }
}

fun Int.toArabic(): String = toString().toArabicNumerals()
fun Long.toArabic(): String = toString().toArabicNumerals()

private val MONTH_NAMES = listOf(
    "يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"
)

/** Accepts "YYYY-MM-DD" or full ISO datetime — returns "١٦ أكتوبر ٢٠٢٦" */
fun formatArabicDate(isoDate: String): String {
    return try {
        val datePart = isoDate.take(10)
        val parts = datePart.split("-")
        val year  = parts[0].toInt()
        val month = parts[1].toInt()
        val day   = parts[2].toInt()
        "${day.toArabic()} ${MONTH_NAMES[month - 1]} ${year.toArabic()}"
    } catch (e: Exception) {
        isoDate
    }
}

/** 12-hour clock: "07:00:00" → "٧:٠٠ صباحًا", "13:30" → "١:٣٠ مساءً", "00:15" → "١٢:١٥ صباحًا". */
fun formatArabicTime(isoTime: String): String {
    return try {
        val (h, m) = isoTime.take(5).split(":").map { it.toInt() }
        val hour12 = if (h % 12 == 0) 12 else h % 12
        val period = if (h < 12) "صباحًا" else "مساءً"
        "${hour12.toArabic()}:${"%02d".format(m).toArabicNumerals()} $period"
    } catch (e: Exception) {
        isoTime.take(5).toArabicNumerals()
    }
}

/** "250 ILS" from server → "٢٥٠ ₪" */
fun String.toArabicAmountDisplay(): String = replace("ILS", "₪").toArabicNumerals()

/** wage_amount (minor units) → "٢٥٠ ₪ / يوم" */
fun formatArabicWage(minorUnits: Long, currency: String, basis: String): String {
    val major = (minorUnits / 100).toArabic()
    val sym = if (currency == "ILS") "₪" else currency
    val basisAr = when (basis) {
        "PER_DAY"  -> "/ يوم"
        "PER_HOUR" -> "/ ساعة"
        "PER_TASK" -> "/ مهمة"
        else       -> ""
    }
    return "$major $sym $basisAr"
}

/** "+970599123456" → "0599123456" (how people type and read Palestinian mobiles); null → "". */
fun String?.toLocalPhone(): String = when {
    this.isNullOrBlank() -> ""
    startsWith("+970") -> "0" + removePrefix("+970")
    startsWith("+972") -> "0" + removePrefix("+972")
    else -> this
}
