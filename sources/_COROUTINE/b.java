package _COROUTINE;

import android.R;
import android.database.Cursor;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.LayerDrawable;
import android.graphics.drawable.PaintDrawable;
import android.graphics.drawable.ShapeDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.Parcel;
import android.os.ParcelFileDescriptor;
import android.os.Parcelable;
import androidx.core.app.NotificationCompat;
import androidx.datastore.core.NativeSharedCounter;
import androidx.datastore.core.h1;
import androidx.datastore.preferences.protobuf.k;
import androidx.room.util.d;
import androidx.work.impl.utils.futures.h;
import com.android.billingclient.api.p0;
import com.appbrain.i.h0;
import com.google.android.play.core.assetpacks.internal.e;
import com.google.android.play.core.assetpacks.r0;
import com.google.android.play.core.assetpacks.u;
import com.google.common.util.concurrent.f;
import com.google.common.util.concurrent.q;
import com.google.common.util.concurrent.r;
import com.google.common.util.concurrent.t0;
import com.google.firebase.crashlytics.internal.model.t1;
import java.io.BufferedInputStream;
import java.io.Closeable;
import java.io.DataInputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.List;
import java.util.TreeMap;
import kotlin.collections.builders.c;
import kotlin.collections.j;
import kotlin.g;

/* JADX INFO: loaded from: classes.dex */
public abstract class b {
    public final /* synthetic */ int u;

    public /* synthetic */ b(int i) {
        this.u = i;
    }

    public static void A(Parcel parcel, int i) {
        if (parcel.dataPosition() != i) {
            throw new com.google.android.gms.common.internal.safeparcel.b(h0.l(i, "Overread allowed size end=", new StringBuilder(String.valueOf(i).length() + 26)), parcel);
        }
    }

    public static boolean H(Parcel parcel, int i) {
        R(parcel, i, 4);
        return parcel.readInt() != 0;
    }

    public static final List I(Cursor cursor) {
        int columnIndex = cursor.getColumnIndex("id");
        int columnIndex2 = cursor.getColumnIndex("seq");
        int columnIndex3 = cursor.getColumnIndex("from");
        int columnIndex4 = cursor.getColumnIndex("to");
        c cVar = new c(10);
        while (cursor.moveToNext()) {
            int i = cursor.getInt(columnIndex);
            int i2 = cursor.getInt(columnIndex2);
            String string = cursor.getString(columnIndex3);
            string.getClass();
            String string2 = cursor.getString(columnIndex4);
            string2.getClass();
            cVar.add(new androidx.room.util.c(i, i2, string, string2));
        }
        c cVarC = p0.c(cVar);
        cVarC.getClass();
        if (cVarC.a() <= 1) {
            return j.B(cVarC);
        }
        Object[] array = cVarC.toArray(new Comparable[0]);
        Comparable[] comparableArr = (Comparable[]) array;
        if (comparableArr.length > 1) {
            Arrays.sort(comparableArr);
        }
        List listAsList = Arrays.asList(array);
        listAsList.getClass();
        return listAsList;
    }

    public static IBinder J(Parcel parcel, int i) {
        int iN = N(parcel, i);
        int iDataPosition = parcel.dataPosition();
        if (iN == 0) {
            return null;
        }
        IBinder strongBinder = parcel.readStrongBinder();
        parcel.setDataPosition(iDataPosition + iN);
        return strongBinder;
    }

    public static final d K(androidx.sqlite.db.framework.c cVar, String str, boolean z) throws IOException {
        Cursor cursorM = cVar.m(new androidx.sqlite.db.a(androidx.privacysandbox.ads.adservices.java.internal.a.g("PRAGMA index_xinfo(`", str, "`)"), (byte) 0));
        try {
            int columnIndex = cursorM.getColumnIndex("seqno");
            int columnIndex2 = cursorM.getColumnIndex("cid");
            int columnIndex3 = cursorM.getColumnIndex("name");
            int columnIndex4 = cursorM.getColumnIndex("desc");
            if (columnIndex != -1 && columnIndex2 != -1 && columnIndex3 != -1 && columnIndex4 != -1) {
                TreeMap treeMap = new TreeMap();
                TreeMap treeMap2 = new TreeMap();
                while (cursorM.moveToNext()) {
                    if (cursorM.getInt(columnIndex2) >= 0) {
                        int i = cursorM.getInt(columnIndex);
                        String string = cursorM.getString(columnIndex3);
                        String str2 = cursorM.getInt(columnIndex4) > 0 ? "DESC" : "ASC";
                        Integer numValueOf = Integer.valueOf(i);
                        string.getClass();
                        treeMap.put(numValueOf, string);
                        treeMap2.put(Integer.valueOf(i), str2);
                    }
                }
                Collection collectionValues = treeMap.values();
                collectionValues.getClass();
                List listB = j.B(collectionValues);
                Collection collectionValues2 = treeMap2.values();
                collectionValues2.getClass();
                d dVar = new d(str, z, listB, j.B(collectionValues2));
                cursorM.close();
                return dVar;
            }
            cursorM.close();
            return null;
        } catch (Throwable th) {
            try {
                throw th;
            } catch (Throwable th2) {
                o(cursorM, th);
                throw th2;
            }
        }
    }

    public static int L(Parcel parcel, int i) {
        R(parcel, i, 4);
        return parcel.readInt();
    }

    public static long M(Parcel parcel, int i) {
        R(parcel, i, 8);
        return parcel.readLong();
    }

    public static int N(Parcel parcel, int i) {
        return (i & (-65536)) != -65536 ? (char) (i >> 16) : parcel.readInt();
    }

    public static void O(Parcel parcel, int i) {
        parcel.setDataPosition(parcel.dataPosition() + N(parcel, i));
    }

    public static final void P(Object obj) throws Throwable {
        if (obj instanceof g) {
            throw ((g) obj).u;
        }
    }

    public static int Q(Parcel parcel) {
        int i = parcel.readInt();
        int iN = N(parcel, i);
        char c = (char) i;
        int iDataPosition = parcel.dataPosition();
        if (c != 20293) {
            throw new com.google.android.gms.common.internal.safeparcel.b("Expected object header. Got 0x".concat(String.valueOf(Integer.toHexString(i))), parcel);
        }
        int i2 = iN + iDataPosition;
        if (i2 >= iDataPosition && i2 <= parcel.dataSize()) {
            return i2;
        }
        StringBuilder sb = new StringBuilder(String.valueOf(iDataPosition).length() + 32 + String.valueOf(i2).length());
        sb.append("Size read is invalid start=");
        sb.append(iDataPosition);
        sb.append(" end=");
        sb.append(i2);
        throw new com.google.android.gms.common.internal.safeparcel.b(sb.toString(), parcel);
    }

    public static void R(Parcel parcel, int i, int i2) {
        int iN = N(parcel, i);
        if (iN == i2) {
            return;
        }
        String hexString = Integer.toHexString(iN);
        int length = String.valueOf(i2).length();
        StringBuilder sb = new StringBuilder(String.valueOf(hexString).length() + length + 19 + String.valueOf(iN).length() + 4 + 1);
        sb.append("Expected size ");
        sb.append(i2);
        sb.append(" got ");
        sb.append(iN);
        throw new com.google.android.gms.common.internal.safeparcel.b(androidx.privacysandbox.ads.adservices.java.internal.a.i(sb, " (0x", hexString, ")"), parcel);
    }

    public static void S(Parcel parcel, int i, int i2) {
        if (i == i2) {
            return;
        }
        String hexString = Integer.toHexString(i);
        int length = String.valueOf(i2).length();
        StringBuilder sb = new StringBuilder(String.valueOf(hexString).length() + length + 19 + String.valueOf(i).length() + 4 + 1);
        sb.append("Expected size ");
        sb.append(i2);
        sb.append(" got ");
        sb.append(i);
        throw new com.google.android.gms.common.internal.safeparcel.b(androidx.privacysandbox.ads.adservices.java.internal.a.i(sb, " (0x", hexString, ")"), parcel);
    }

    public static LayerDrawable c(ShapeDrawable shapeDrawable, int i) {
        PaintDrawable paintDrawable = new PaintDrawable(i);
        try {
            paintDrawable.setShape(shapeDrawable.getShape().clone());
            return new LayerDrawable(new Drawable[]{shapeDrawable, paintDrawable});
        } catch (CloneNotSupportedException unused) {
            androidx.core.graphics.drawable.a.j("ShapeDrawable's Shape should implement clone()");
            return null;
        }
    }

    public static StateListDrawable d(ShapeDrawable shapeDrawable) {
        LayerDrawable layerDrawableC = c(shapeDrawable, 1140850688);
        LayerDrawable layerDrawableC2 = c(shapeDrawable, 1157627903);
        StateListDrawable stateListDrawable = new StateListDrawable();
        stateListDrawable.addState(new int[]{R.attr.state_pressed}, layerDrawableC);
        stateListDrawable.addState(new int[]{R.attr.state_focused}, layerDrawableC2);
        stateListDrawable.addState(new int[]{R.attr.state_selected}, layerDrawableC2);
        stateListDrawable.addState(new int[0], shapeDrawable);
        return stateListDrawable;
    }

    public static com.appbrain.h.a e(int i, int i2, int i3, int i4, float f) {
        com.appbrain.h.a aVar = new com.appbrain.h.a(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{i, i2});
        aVar.setStroke(i4, i3);
        aVar.setCornerRadius(f);
        return aVar;
    }

    public static void f(u uVar, InputStream inputStream, r0 r0Var, long j) throws Throwable {
        r0 r0Var2;
        DataInputStream dataInputStream;
        u uVar2;
        int unsignedShort;
        byte[] bArr = new byte[16384];
        DataInputStream dataInputStream2 = new DataInputStream(new BufferedInputStream(inputStream, NotificationCompat.FLAG_BUBBLE));
        int i = dataInputStream2.readInt();
        if (i != -771763713) {
            throw new k("Unexpected magic=".concat(String.format("%x", Integer.valueOf(i))));
        }
        int i2 = dataInputStream2.read();
        if (i2 != 4) {
            throw new k(androidx.privacysandbox.ads.adservices.java.internal.a.c(i2, "Unexpected version="));
        }
        long j2 = 0;
        while (true) {
            long j3 = j - j2;
            try {
                int unsignedShort2 = dataInputStream2.read();
                if (unsignedShort2 == -1) {
                    throw new IOException("Patch file overrun");
                }
                if (unsignedShort2 == 0) {
                    r0Var.flush();
                    return;
                }
                switch (unsignedShort2) {
                    case 247:
                        r0Var2 = r0Var;
                        unsignedShort2 = dataInputStream2.readUnsignedShort();
                        h(bArr, dataInputStream2, r0Var2, unsignedShort2, j3);
                        j2 += (long) unsignedShort2;
                        r0Var = r0Var2;
                        break;
                    case 248:
                        r0Var2 = r0Var;
                        unsignedShort2 = dataInputStream2.readInt();
                        h(bArr, dataInputStream2, r0Var2, unsignedShort2, j3);
                        j2 += (long) unsignedShort2;
                        r0Var = r0Var2;
                        break;
                    case 249:
                        r0Var2 = r0Var;
                        DataInputStream dataInputStream3 = dataInputStream2;
                        u uVar3 = uVar;
                        long unsignedShort3 = dataInputStream3.readUnsignedShort();
                        int i3 = dataInputStream3.read();
                        if (i3 == -1) {
                            throw new IOException("Unexpected end of patch");
                        }
                        g(bArr, uVar3, r0Var2, unsignedShort3, i3, j3);
                        uVar = uVar3;
                        dataInputStream2 = dataInputStream3;
                        unsignedShort2 = i3;
                        j2 += (long) unsignedShort2;
                        r0Var = r0Var2;
                        break;
                        break;
                    case 250:
                        r0Var2 = r0Var;
                        dataInputStream = dataInputStream2;
                        uVar2 = uVar;
                        long unsignedShort4 = dataInputStream.readUnsignedShort();
                        unsignedShort = dataInputStream.readUnsignedShort();
                        g(bArr, uVar2, r0Var2, unsignedShort4, unsignedShort, j3);
                        uVar = uVar2;
                        unsignedShort2 = unsignedShort;
                        dataInputStream2 = dataInputStream;
                        j2 += (long) unsignedShort2;
                        r0Var = r0Var2;
                        break;
                    case 251:
                        r0Var2 = r0Var;
                        dataInputStream = dataInputStream2;
                        uVar2 = uVar;
                        long unsignedShort5 = dataInputStream.readUnsignedShort();
                        unsignedShort = dataInputStream.readInt();
                        g(bArr, uVar2, r0Var2, unsignedShort5, unsignedShort, j3);
                        uVar = uVar2;
                        unsignedShort2 = unsignedShort;
                        dataInputStream2 = dataInputStream;
                        j2 += (long) unsignedShort2;
                        r0Var = r0Var2;
                        break;
                    case 252:
                        r0Var2 = r0Var;
                        dataInputStream = dataInputStream2;
                        uVar2 = uVar;
                        long j4 = dataInputStream.readInt();
                        unsignedShort = dataInputStream.read();
                        if (unsignedShort == -1) {
                            throw new IOException("Unexpected end of patch");
                        }
                        g(bArr, uVar2, r0Var2, j4, unsignedShort, j3);
                        uVar = uVar2;
                        unsignedShort2 = unsignedShort;
                        dataInputStream2 = dataInputStream;
                        j2 += (long) unsignedShort2;
                        r0Var = r0Var2;
                        break;
                        break;
                    case 253:
                        r0Var2 = r0Var;
                        dataInputStream = dataInputStream2;
                        uVar2 = uVar;
                        long j5 = dataInputStream.readInt();
                        unsignedShort = dataInputStream.readUnsignedShort();
                        g(bArr, uVar2, r0Var2, j5, unsignedShort, j3);
                        uVar = uVar2;
                        unsignedShort2 = unsignedShort;
                        dataInputStream2 = dataInputStream;
                        j2 += (long) unsignedShort2;
                        r0Var = r0Var2;
                        break;
                    case 254:
                        r0Var2 = r0Var;
                        dataInputStream = dataInputStream2;
                        uVar2 = uVar;
                        long j6 = dataInputStream.readInt();
                        unsignedShort = dataInputStream.readInt();
                        g(bArr, uVar2, r0Var2, j6, unsignedShort, j3);
                        uVar = uVar2;
                        unsignedShort2 = unsignedShort;
                        dataInputStream2 = dataInputStream;
                        j2 += (long) unsignedShort2;
                        r0Var = r0Var2;
                        break;
                    case 255:
                        r0Var2 = r0Var;
                        dataInputStream = dataInputStream2;
                        long j7 = dataInputStream.readLong();
                        unsignedShort = dataInputStream.readInt();
                        uVar2 = uVar;
                        g(bArr, uVar2, r0Var2, j7, unsignedShort, j3);
                        uVar = uVar2;
                        unsignedShort2 = unsignedShort;
                        dataInputStream2 = dataInputStream;
                        j2 += (long) unsignedShort2;
                        r0Var = r0Var2;
                        break;
                    default:
                        r0Var2 = r0Var;
                        try {
                            h(bArr, dataInputStream2, r0Var2, unsignedShort2, j3);
                            dataInputStream = dataInputStream2;
                            dataInputStream2 = dataInputStream;
                            j2 += (long) unsignedShort2;
                            r0Var = r0Var2;
                        } catch (Throwable th) {
                            th = th;
                            Throwable th2 = th;
                            r0Var2.flush();
                            throw th2;
                        }
                        break;
                }
            } catch (Throwable th3) {
                th = th3;
                r0Var2 = r0Var;
            }
        }
    }

    public static void g(byte[] bArr, u uVar, r0 r0Var, long j, int i, long j2) throws IOException {
        InputStream inputStreamB;
        if (i < 0) {
            androidx.core.graphics.drawable.a.o("copyLength negative");
            return;
        }
        if (j < 0) {
            androidx.core.graphics.drawable.a.o("inputOffset negative");
            return;
        }
        long j3 = i;
        if (j3 > j2) {
            androidx.core.graphics.drawable.a.o("Output length overrun");
            return;
        }
        try {
            e eVar = new e(uVar, j, j3);
            synchronized (eVar) {
                inputStreamB = eVar.b(0L, eVar.w - eVar.v);
            }
            int i2 = i;
            while (i2 > 0) {
                try {
                    int iMin = Math.min(i2, 16384);
                    int i3 = 0;
                    while (i3 < iMin) {
                        int i4 = inputStreamB.read(bArr, i3, iMin - i3);
                        if (i4 == -1) {
                            throw new IOException("truncated input stream");
                        }
                        i3 += i4;
                        throw new IOException("patch underrun", e);
                    }
                    r0Var.write(bArr, 0, iMin);
                    i2 -= iMin;
                } catch (Throwable th) {
                    try {
                        inputStreamB.close();
                        throw th;
                    } catch (Throwable th2) {
                        th.addSuppressed(th2);
                        throw th;
                    }
                }
            }
            inputStreamB.close();
        } catch (EOFException e) {
            throw new IOException("patch underrun", e);
        }
    }

    public static void h(byte[] bArr, DataInputStream dataInputStream, r0 r0Var, int i, long j) throws IOException {
        if (i < 0) {
            androidx.core.graphics.drawable.a.o("copyLength negative");
            return;
        }
        if (i > j) {
            androidx.core.graphics.drawable.a.o("Output length overrun");
            return;
        }
        while (i > 0) {
            try {
                int iMin = Math.min(i, 16384);
                dataInputStream.readFully(bArr, 0, iMin);
                r0Var.write(bArr, 0, iMin);
                i -= iMin;
            } catch (EOFException unused) {
                androidx.core.graphics.drawable.a.o("patch underrun");
                return;
            }
        }
    }

    public static final void o(Closeable closeable, Throwable th) throws IOException {
        if (closeable != null) {
            if (th == null) {
                closeable.close();
                return;
            }
            try {
                closeable.close();
            } catch (Throwable th2) {
                t1.e(th, th2);
            }
        }
    }

    public static Handler p(Looper looper) {
        return Handler.createAsync(looper);
    }

    public static Bundle q(Parcel parcel, int i) {
        int iN = N(parcel, i);
        int iDataPosition = parcel.dataPosition();
        if (iN == 0) {
            return null;
        }
        Bundle bundle = parcel.readBundle();
        parcel.setDataPosition(iDataPosition + iN);
        return bundle;
    }

    public static byte[] r(Parcel parcel, int i) {
        int iN = N(parcel, i);
        int iDataPosition = parcel.dataPosition();
        if (iN == 0) {
            return null;
        }
        byte[] bArrCreateByteArray = parcel.createByteArray();
        parcel.setDataPosition(iDataPosition + iN);
        return bArrCreateByteArray;
    }

    public static byte[][] s(Parcel parcel, int i) {
        int iN = N(parcel, i);
        int iDataPosition = parcel.dataPosition();
        if (iN == 0) {
            return null;
        }
        int i2 = parcel.readInt();
        byte[][] bArr = new byte[i2][];
        for (int i3 = 0; i3 < i2; i3++) {
            bArr[i3] = parcel.createByteArray();
        }
        parcel.setDataPosition(iDataPosition + iN);
        return bArr;
    }

    public static h1 t(ParcelFileDescriptor parcelFileDescriptor) throws IOException {
        int fd = parcelFileDescriptor.getFd();
        NativeSharedCounter nativeSharedCounter = h1.b;
        if (nativeSharedCounter.nativeTruncateFile(fd) != 0) {
            androidx.core.graphics.drawable.a.o("Failed to truncate counter file");
            return null;
        }
        long jNativeCreateSharedCounter = nativeSharedCounter.nativeCreateSharedCounter(fd);
        if (jNativeCreateSharedCounter >= 0) {
            return new h1(jNativeCreateSharedCounter);
        }
        androidx.core.graphics.drawable.a.o("Failed to mmap counter file");
        return null;
    }

    public static final g u(Throwable th) {
        th.getClass();
        return new g(th);
    }

    public static int[] v(Parcel parcel, int i) {
        int iN = N(parcel, i);
        int iDataPosition = parcel.dataPosition();
        if (iN == 0) {
            return null;
        }
        int[] iArrCreateIntArray = parcel.createIntArray();
        parcel.setDataPosition(iDataPosition + iN);
        return iArrCreateIntArray;
    }

    public static Parcelable w(Parcel parcel, int i, Parcelable.Creator creator) {
        int iN = N(parcel, i);
        int iDataPosition = parcel.dataPosition();
        if (iN == 0) {
            return null;
        }
        Parcelable parcelable = (Parcelable) creator.createFromParcel(parcel);
        parcel.setDataPosition(iDataPosition + iN);
        return parcelable;
    }

    public static String x(Parcel parcel, int i) {
        int iN = N(parcel, i);
        int iDataPosition = parcel.dataPosition();
        if (iN == 0) {
            return null;
        }
        String string = parcel.readString();
        parcel.setDataPosition(iDataPosition + iN);
        return string;
    }

    public static Object[] y(Parcel parcel, int i, Parcelable.Creator creator) {
        int iN = N(parcel, i);
        int iDataPosition = parcel.dataPosition();
        if (iN == 0) {
            return null;
        }
        Object[] objArrCreateTypedArray = parcel.createTypedArray(creator);
        parcel.setDataPosition(iDataPosition + iN);
        return objArrCreateTypedArray;
    }

    public static ArrayList z(Parcel parcel, int i, Parcelable.Creator creator) {
        int iN = N(parcel, i);
        int iDataPosition = parcel.dataPosition();
        if (iN == 0) {
            return null;
        }
        ArrayList arrayListCreateTypedArrayList = parcel.createTypedArrayList(creator);
        parcel.setDataPosition(iDataPosition + iN);
        return arrayListCreateTypedArrayList;
    }

    public abstract f B(r rVar);

    public abstract q C(r rVar);

    public abstract void D(androidx.work.impl.utils.futures.g gVar, androidx.work.impl.utils.futures.g gVar2);

    public abstract void E(q qVar, q qVar2);

    public abstract void F(androidx.work.impl.utils.futures.g gVar, Thread thread);

    public abstract void G(q qVar, Thread thread);

    public abstract boolean i(h hVar, androidx.work.impl.utils.futures.c cVar, androidx.work.impl.utils.futures.c cVar2);

    public abstract boolean j(r rVar, f fVar, f fVar2);

    public abstract boolean k(h hVar, Object obj, Object obj2);

    public abstract boolean l(r rVar, Object obj, Object obj2);

    public abstract boolean m(h hVar, androidx.work.impl.utils.futures.g gVar, androidx.work.impl.utils.futures.g gVar2);

    public abstract boolean n(r rVar, q qVar, q qVar2);

    public String toString() {
        switch (this.u) {
            case 8:
                return ((t0) this).v.toString();
            default:
                return super.toString();
        }
    }
}
