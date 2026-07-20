package _COROUTINE;

import android.database.Cursor;
import android.os.Build;
import androidx.datastore.core.e;
import androidx.datastore.core.g;
import androidx.datastore.core.k;
import androidx.room.t;
import androidx.work.impl.WorkDatabase;
import androidx.work.impl.WorkDatabase_Impl;
import androidx.work.impl.o;
import androidx.work.r;
import com.appbrain.e.i;
import com.google.android.gms.common.api.Status;
import com.google.android.gms.common.api.j;
import com.google.firebase.crashlytics.internal.model.t1;
import com.google.firebase.remoteconfig.internal.Code;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.NoSuchElementException;
import kotlin.coroutines.jvm.internal.c;
import kotlin.d;
import kotlin.jvm.functions.l;
import kotlin.jvm.internal.h;
import kotlin.jvm.internal.p;
import kotlin.jvm.internal.q;

/* JADX INFO: loaded from: classes.dex */
public abstract class a {

    /* JADX INFO: renamed from: a, reason: collision with root package name */
    public final /* synthetic */ int f0a = 12;

    public static String a(i iVar) {
        String str;
        StringBuilder sb = new StringBuilder(iVar.c());
        for (int i = 0; i < iVar.c(); i++) {
            int iA = iVar.a(i);
            if (iA == 34) {
                str = "\\\"";
            } else if (iA == 39) {
                str = "\\'";
            } else if (iA != 92) {
                switch (iA) {
                    case 7:
                        str = "\\a";
                        break;
                    case 8:
                        str = "\\b";
                        break;
                    case 9:
                        str = "\\t";
                        break;
                    case 10:
                        str = "\\n";
                        break;
                    case Code.OUT_OF_RANGE /* 11 */:
                        str = "\\v";
                        break;
                    case 12:
                        str = "\\f";
                        break;
                    case Code.INTERNAL /* 13 */:
                        str = "\\r";
                        break;
                    default:
                        if (iA < 32 || iA > 126) {
                            sb.append('\\');
                            sb.append((char) (((iA >>> 6) & 3) + 48));
                            sb.append((char) (((iA >>> 3) & 7) + 48));
                            iA = (iA & 7) + 48;
                        }
                        sb.append((char) iA);
                        continue;
                        break;
                }
            } else {
                str = "\\\\";
            }
            sb.append(str);
        }
        return sb.toString();
    }

    public static String b(File file) {
        if (!file.getName().endsWith(".apk")) {
            androidx.core.graphics.drawable.a.j("Non-apk found in splits directory.");
            return null;
        }
        String strReplaceFirst = file.getName().replaceFirst("(_\\d+)?\\.apk", "");
        if (strReplaceFirst.equals("base-master") || strReplaceFirst.equals("base-main")) {
            return "";
        }
        return strReplaceFirst.startsWith("base-") ? strReplaceFirst.replace("base-", "config.") : strReplaceFirst.replace("-", ".config.").replace(".config.master", "").replace(".config.main", "");
    }

    public static final StackTraceElement c(Exception exc, String str) {
        StackTraceElement stackTraceElement = exc.getStackTrace()[0];
        return new StackTraceElement("_COROUTINE.".concat(str), "_", stackTraceElement.getFileName(), stackTraceElement.getLineNumber());
    }

    /* JADX WARN: Code duplicated, block: B:27:0x0069  */
    /* JADX WARN: Code duplicated, block: B:37:0x008f  */
    /* JADX WARN: Code duplicated, block: B:39:0x0092  */
    /* JADX WARN: Code duplicated, block: B:43:0x0091 A[SYNTHETIC] */
    /* JADX WARN: Code duplicated, block: B:45:? A[LOOP:0: B:25:0x0063->B:45:?, LOOP_END, SYNTHETIC] */
    /* JADX WARN: Code duplicated, block: B:7:0x0013  */
    /* JADX WARN: Unsupported multi-entry loop pattern (BACK_EDGE: B:33:0x0080 -> B:25:0x0063). Please report as a decompilation issue!!! */
    /* JADX WARN: Unsupported multi-entry loop pattern (BACK_EDGE: B:34:0x0083 -> B:25:0x0063). Please report as a decompilation issue!!! */
    public static final Object d(List list, k kVar, c cVar) throws Throwable {
        e eVar;
        List list2;
        p pVar;
        Iterator it;
        Throwable th;
        l lVar;
        if (cVar instanceof e) {
            eVar = (e) cVar;
            int i = eVar.A;
            if ((i & Integer.MIN_VALUE) != 0) {
                eVar.A = i - Integer.MIN_VALUE;
            } else {
                eVar = new e(cVar);
            }
        } else {
            eVar = new e(cVar);
        }
        Object obj = eVar.z;
        int i2 = eVar.A;
        Object obj2 = kotlin.coroutines.intrinsics.a.u;
        if (i2 != 0) {
            if (i2 == 1) {
                list2 = (List) eVar.x;
                b.P(obj);
            } else {
                if (i2 != 2) {
                    androidx.core.graphics.drawable.a.u("call to 'resume' before 'invoke' with coroutine");
                    return null;
                }
                it = eVar.y;
                pVar = (p) eVar.x;
                try {
                    b.P(obj);
                } catch (Throwable th2) {
                    Object obj3 = pVar.u;
                    if (obj3 == null) {
                        pVar.u = th2;
                    } else {
                        t1.e((Throwable) obj3, th2);
                    }
                }
            }
            while (it.hasNext()) {
                lVar = (l) it.next();
                eVar.x = pVar;
                eVar.y = it;
                eVar.A = 2;
                if (lVar.h(eVar) == obj2) {
                    return obj2;
                }
            }
            th = (Throwable) pVar.u;
            if (th == null) {
                return kotlin.l.f1158a;
            }
            throw th;
        }
        b.P(obj);
        ArrayList arrayList = new ArrayList();
        g gVar = new g(list, arrayList, null);
        eVar.x = arrayList;
        eVar.A = 1;
        if (kVar.a(gVar, eVar) == obj2) {
            return obj2;
        }
        list2 = arrayList;
        pVar = new p();
        it = list2.iterator();
        while (it.hasNext()) {
            lVar = (l) it.next();
            eVar.x = pVar;
            eVar.y = it;
            eVar.A = 2;
            if (lVar.h(eVar) == obj2) {
                return obj2;
            }
        }
        th = (Throwable) pVar.u;
        if (th == null) {
            return kotlin.l.f1158a;
        }
        throw th;
    }

    public static final void e(WorkDatabase workDatabase, androidx.work.a aVar, o oVar) {
        int i;
        workDatabase.getClass();
        aVar.getClass();
        oVar.getClass();
        if (Build.VERSION.SDK_INT < 24) {
            return;
        }
        ArrayList arrayList = new ArrayList(new kotlin.collections.g(new o[]{oVar}, true));
        int i2 = 0;
        while (!arrayList.isEmpty()) {
            if (arrayList.isEmpty()) {
                throw new NoSuchElementException("List is empty.");
            }
            List list = ((o) arrayList.remove(arrayList.size() - 1)).d;
            list.getClass();
            if (list.isEmpty()) {
                i = 0;
            } else {
                Iterator it = list.iterator();
                i = 0;
                while (it.hasNext()) {
                    if (((r) it.next()).b.j.a() && (i = i + 1) < 0) {
                        throw new ArithmeticException("Count overflow has happened.");
                    }
                }
            }
            i2 += i;
        }
        if (i2 == 0) {
            return;
        }
        androidx.work.impl.model.p pVarT = workDatabase.t();
        pVarT.getClass();
        t tVarF = t.f(0, "Select COUNT(*) FROM workspec WHERE LENGTH(content_uri_triggers)<>0 AND state NOT IN (2, 3, 5)");
        WorkDatabase_Impl workDatabase_Impl = pVarT.f209a;
        workDatabase_Impl.b();
        Cursor cursorM = workDatabase_Impl.m(tVarF);
        try {
            int i3 = cursorM.moveToFirst() ? cursorM.getInt(0) : 0;
            cursorM.close();
            tVarF.h();
            int i4 = aVar.i;
            if (i3 + i2 <= i4) {
                return;
            }
            StringBuilder sb = new StringBuilder("Too many workers with contentUriTriggers are enqueued:\ncontentUriTrigger workers limit: ");
            sb.append(i4);
            sb.append(";\nalready enqueued count: ");
            sb.append(i3);
            sb.append(";\ncurrent enqueue operation count: ");
            androidx.core.graphics.drawable.a.j(androidx.privacysandbox.ads.adservices.java.internal.a.d(i2, ".\nTo address this issue you can: \n1. enqueue less workers or batch some of workers with content uri triggers together;\n2. increase limit via Configuration.Builder.setContentUriTriggerWorkersLimit;\nPlease beware that workers with content uri triggers immediately occupy slots in JobScheduler so no updates to content uris are missed.", sb));
        } catch (Throwable th) {
            cursorM.close();
            tVarF.h();
            throw th;
        }
    }

    public static void f(int i, String str) {
        if (i >= 0) {
            return;
        }
        StringBuilder sb = new StringBuilder(str.length() + 40);
        sb.append(str);
        sb.append(" cannot be negative but was: ");
        sb.append(i);
        throw new IllegalArgumentException(sb.toString());
    }

    public static boolean g(String str, String str2) {
        str.getClass();
        if (str.equals(str2)) {
            return true;
        }
        if (str.length() != 0) {
            int i = 0;
            int i2 = 0;
            int i3 = 0;
            while (i < str.length()) {
                char cCharAt = str.charAt(i);
                int i4 = i3 + 1;
                if (i3 != 0 || cCharAt == '(') {
                    if (cCharAt == '(') {
                        i2++;
                    } else if (cCharAt != ')' || (i2 = i2 - 1) != 0 || i3 == str.length() - 1) {
                    }
                    i++;
                    i3 = i4;
                }
            }
            if (i2 == 0) {
                String strSubstring = str.substring(1, str.length() - 1);
                int length = strSubstring.length() - 1;
                int i5 = 0;
                boolean z = false;
                while (i5 <= length) {
                    char cCharAt2 = strSubstring.charAt(!z ? i5 : length);
                    boolean z2 = Character.isWhitespace(cCharAt2) || Character.isSpaceChar(cCharAt2);
                    if (z) {
                        if (!z2) {
                            break;
                        }
                        length--;
                    } else if (z2) {
                        i5++;
                    } else {
                        z = true;
                    }
                }
                return h.a(strSubstring.subSequence(i5, length + 1).toString(), str2);
            }
        }
        return false;
    }

    /* JADX WARN: Code restructure failed: missing block: B:14:0x0037, code lost:
    
        if (r0 > 0) goto L19;
     */
    /* JADX WARN: Code restructure failed: missing block: B:16:0x003a, code lost:
    
        if (r4 > 0) goto L19;
     */
    /* JADX WARN: Code restructure failed: missing block: B:18:0x003d, code lost:
    
        if (r4 < 0) goto L19;
     */
    /*
        Code decompiled incorrectly, please refer to instructions dump.
        To view partially-correct add '--show-bad-code' argument
    */
    public static int h(int r4, int r5) {
        /*
            java.math.RoundingMode r0 = java.math.RoundingMode.CEILING
            r0.getClass()
            if (r5 == 0) goto L4c
            int r1 = r4 / r5
            int r2 = r5 * r1
            int r2 = r4 - r2
            if (r2 != 0) goto L10
            goto L43
        L10:
            r4 = r4 ^ r5
            int r4 = r4 >> 31
            r4 = r4 | 1
            int[] r3 = com.google.common.math.a.f912a
            int r0 = r0.ordinal()
            r0 = r3[r0]
            switch(r0) {
                case 1: goto L41;
                case 2: goto L43;
                case 3: goto L3d;
                case 4: goto L3f;
                case 5: goto L3a;
                case 6: goto L26;
                case 7: goto L26;
                case 8: goto L26;
                default: goto L20;
            }
        L20:
            java.lang.AssertionError r4 = new java.lang.AssertionError
            r4.<init>()
            throw r4
        L26:
            int r0 = java.lang.Math.abs(r2)
            int r5 = java.lang.Math.abs(r5)
            int r5 = r5 - r0
            int r0 = r0 - r5
            if (r0 != 0) goto L37
            java.math.RoundingMode r4 = java.math.RoundingMode.HALF_UP
            java.math.RoundingMode r4 = java.math.RoundingMode.HALF_EVEN
            goto L43
        L37:
            if (r0 <= 0) goto L43
            goto L3f
        L3a:
            if (r4 <= 0) goto L43
            goto L3f
        L3d:
            if (r4 >= 0) goto L43
        L3f:
            int r1 = r1 + r4
            return r1
        L41:
            if (r2 != 0) goto L44
        L43:
            return r1
        L44:
            java.lang.ArithmeticException r4 = new java.lang.ArithmeticException
            java.lang.String r5 = "mode was UNNECESSARY, but rounding was necessary"
            r4.<init>(r5)
            throw r4
        L4c:
            java.lang.ArithmeticException r4 = new java.lang.ArithmeticException
            java.lang.String r5 = "/ by zero"
            r4.<init>(r5)
            throw r4
        */
        throw new UnsupportedOperationException("Method not decompiled: _COROUTINE.a.h(int, int):int");
    }

    public static d i(kotlin.jvm.functions.a aVar) {
        kotlin.k kVar = kotlin.k.f1157a;
        kotlin.i iVar = new kotlin.i();
        iVar.u = aVar;
        iVar.v = kVar;
        return iVar;
    }

    public static int j(int i) {
        RoundingMode roundingMode = RoundingMode.UNNECESSARY;
        if (i <= 0) {
            StringBuilder sb = new StringBuilder(27);
            sb.append("x (");
            sb.append(i);
            sb.append(") must be > 0");
            throw new IllegalArgumentException(sb.toString());
        }
        switch (com.google.common.math.a.f912a[roundingMode.ordinal()]) {
            case 1:
                if (!((i > 0) & (((i + (-1)) & i) == 0))) {
                    throw new ArithmeticException("mode was UNNECESSARY, but rounding was necessary");
                }
                break;
            case 2:
            case 3:
                break;
            case 4:
            case 5:
                return 32 - Integer.numberOfLeadingZeros(i - 1);
            case 6:
            case 7:
            case 8:
                int iNumberOfLeadingZeros = Integer.numberOfLeadingZeros(i);
                return (31 - iNumberOfLeadingZeros) + ((~(~(((-1257966797) >>> iNumberOfLeadingZeros) - i))) >>> 31);
            default:
                throw new AssertionError();
        }
        return 31 - Integer.numberOfLeadingZeros(i);
    }

    public static final byte[] k(FileInputStream fileInputStream) throws IOException {
        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream(Math.max(8192, fileInputStream.available()));
        byte[] bArr = new byte[8192];
        int i = fileInputStream.read(bArr);
        while (i >= 0) {
            byteArrayOutputStream.write(bArr, 0, i);
            i = fileInputStream.read(bArr);
        }
        byte[] byteArray = byteArrayOutputStream.toByteArray();
        byteArray.getClass();
        return byteArray;
    }

    public static void l(Status status, Object obj, com.google.android.gms.tasks.h hVar) {
        if (status.u <= 0) {
            hVar.f852a.k(obj);
        } else {
            hVar.f852a.m(status.w != null ? new j(status) : new com.google.android.gms.common.api.d(status));
        }
    }

    public int hashCode() {
        switch (this.f0a) {
            case 12:
                return toString().hashCode();
            default:
                return super.hashCode();
        }
    }

    public String toString() {
        switch (this.f0a) {
            case 12:
                String strB = q.a(getClass()).b();
                strB.getClass();
                return strB;
            default:
                return super.toString();
        }
    }
}
