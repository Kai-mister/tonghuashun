package cn.local.simmanager;

import java.time.*;

/** Wall-clock windows always use Shanghai, independent of the phone time zone. */
public final class WatchSchedule {
    static final ZoneId ZONE=ZoneId.of("Asia/Shanghai");
    static final LocalTime MORNING=LocalTime.of(9,14), NOON=LocalTime.of(11,31);
    static final LocalTime AFTERNOON=LocalTime.of(12,59), END=LocalTime.of(15,1);
    static boolean weekday(LocalDate day){return day.getDayOfWeek().getValue()<=5;}
    public static boolean active(long millis){
        ZonedDateTime now=Instant.ofEpochMilli(millis).atZone(ZONE);
        LocalTime t=now.toLocalTime();
        return weekday(now.toLocalDate()) && ((!t.isBefore(MORNING)&&t.isBefore(NOON)) ||
                (!t.isBefore(AFTERNOON)&&t.isBefore(END)));
    }
    public static long next(long millis){
        ZonedDateTime now=Instant.ofEpochMilli(millis).atZone(ZONE);
        // System-alarm fallback during trading: a frozen app timer must not miss
        // the configured buy minute or the 14:50 exit check.
        if(active(millis))return now.withSecond(0).withNano(0).plusMinutes(1).toInstant().toEpochMilli();
        for(int i=0;i<8;i++){
            LocalDate day=now.toLocalDate().plusDays(i);
            if(!weekday(day))continue;
            for(LocalTime time:new LocalTime[]{MORNING,AFTERNOON}){
                long at=ZonedDateTime.of(day,time,ZONE).toInstant().toEpochMilli();
                if(at>millis)return at;
            }
        }
        throw new IllegalStateException("No next weekday");
    }
    public static String display(long millis){
        return Instant.ofEpochMilli(millis).atZone(ZONE).format(java.time.format.DateTimeFormatter.ofPattern("MM-dd HH:mm"));
    }
}
