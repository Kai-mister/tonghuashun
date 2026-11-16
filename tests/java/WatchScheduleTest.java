package cn.local.simmanager;
import java.time.*;
public class WatchScheduleTest {
    static long at(String text){return LocalDateTime.parse(text).atZone(WatchSchedule.ZONE).toInstant().toEpochMilli();}
    static void expect(boolean value){if(!value)throw new AssertionError();}
    public static void main(String[] args){
        expect(!WatchSchedule.active(at("2026-11-16T09:13:59")));
        expect(WatchSchedule.active(at("2026-11-16T09:14:00")));
        expect(WatchSchedule.active(at("2026-11-16T09:20:00")));
        expect(!WatchSchedule.active(at("2026-11-16T11:31:00")));
        expect(WatchSchedule.active(at("2026-11-16T12:59:00")));
        expect(WatchSchedule.active(at("2026-11-16T14:50:00")));
        expect(!WatchSchedule.active(at("2026-11-16T15:01:00")));
        expect(!WatchSchedule.active(at("2026-11-14T09:20:00")));
        expect(WatchSchedule.next(at("2026-11-13T15:02:00"))==at("2026-11-16T09:14:00"));
        expect(WatchSchedule.next(at("2026-11-16T09:14:00"))==at("2026-11-16T09:15:00"));
        expect(WatchSchedule.next(at("2026-11-16T12:59:00"))==at("2026-11-16T13:00:00"));
        expect(WatchSchedule.next(at("2026-11-16T09:19:59"))==at("2026-11-16T09:20:00"));
        expect(WatchSchedule.next(at("2026-11-16T14:49:30"))==at("2026-11-16T14:50:00"));
        expect(WatchSchedule.next(at("2026-11-16T11:31:00"))==at("2026-11-16T12:59:00"));
        expect(WatchSchedule.next(at("2026-11-16T15:01:00"))==at("2026-11-17T09:14:00"));
        System.out.println("PASS: weekday, morning/afternoon wake windows, Shanghai time, weekend rollover");
    }
}
