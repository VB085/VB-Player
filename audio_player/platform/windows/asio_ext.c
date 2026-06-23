/** ASIO Native Backend — full buffer management replacing GStreamer asiosink. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objbase.h>
#include <process.h>

enum { VI_INIT=3, VI_START=7, VI_STOP=8, VI_GETCH=9, VI_GETBS=11,
       VI_CANRATE=12, VI_GETRATE=13, VI_SETRATE=14, VI_CRBUF=19,
       VI_DISPBUF=20, VI_OUTRDY=23 };

typedef long ASErr;
#define VC(p,i,r,...) ((r(*)(void*,##__VA_ARGS__))(((void**)(*(void***)p))[i]))

static CLSID mkclsid(const char*s){wchar_t w[64]={0};MultiByteToWideChar(CP_UTF8,0,s,-1,w,64);CLSID c={0};CLSIDFromString(w,&c);return c;}

static void *g_a;static char **g_b;static long g_bs,g_ch;static volatile int g_nd;
static HANDLE g_ev;

static long _cdecl cbBS(long i,long d){(void)i;(void)d;g_nd=1;SetEvent(g_ev);return 0;}
static void _cdecl cbTI(void*p,long i,long d){cbBS(i,d);}
static ASErr _cdecl cbSR(double r){(void)r;return 0;}
static long _cdecl cbAM(long s,long v,void*m,double*o){(void)s;(void)v;(void)m;(void)o;return 0;}
struct CB{void*bs;void*sr;void*am;void*ti;};

static PyObject* asio_open(PyObject*s,PyObject*a){
    const char*cs;double r;if(!PyArg_ParseTuple(a,"sd",&cs,&r))return NULL;
    if(g_a)Py_RETURN_FALSE;
    CoInitializeEx(NULL,2);CLSID c=mkclsid(cs);void*p=NULL;
    if(FAILED(CoCreateInstance(&c,NULL,CLSCTX_INPROC_SERVER,(IID*)&c,&p))||!p)Py_RETURN_FALSE;
    if(VC(p,VI_INIT,long,void*)(p,NULL)!=1){VC(p,2,unsigned long)(p);Py_RETURN_FALSE;}
    if(VC(p,VI_SETRATE,ASErr,double)(p,r)){VC(p,2,unsigned long)(p);Py_RETURN_FALSE;}
    long ic=0,oc=0;VC(p,VI_GETCH,ASErr,long*,long*)(p,&ic,&oc);if(oc<2)oc=2;
    long mn=0,mx=0,pf=0,gr=0;VC(p,VI_GETBS,ASErr,long*,long*,long*,long*)(p,&mn,&mx,&pf,&gr);
    long bs=pf?pf:(mx?mx:1024);if(bs<64)bs=1024;
    typedef struct{long isIn;long ch;void*b[2];}BI;
    BI*bi=calloc(oc,sizeof(BI));for(long i=0;i<oc;i++){bi[i].isIn=0;bi[i].ch=i;}
    struct CB cb={cbBS,cbSR,cbAM,cbTI};
    if(VC(p,VI_CRBUF,ASErr,void*,long,long,void*)(p,bi,oc,bs,&cb)){
        free(bi);VC(p,2,unsigned long)(p);Py_RETURN_FALSE;}
    char**bb=calloc(oc,sizeof(char*));for(long i=0;i<oc;i++)bb[i]=bi[i].b[0];free(bi);
    VC(p,VI_START,ASErr)(p);
    g_a=p;g_b=bb;g_bs=bs;g_ch=oc;g_ev=CreateEvent(NULL,0,0,NULL);
    return Py_BuildValue("ll",oc,bs);}

static PyObject* asio_write(PyObject*s,PyObject*a){
    Py_buffer v;if(!PyArg_ParseTuple(a,"y*",&v))return NULL;
    if(!g_a){PyBuffer_Release(&v);Py_RETURN_FALSE;}
    float*sr=(float*)v.buf;long ns=v.len/sizeof(float)/g_ch;if(ns>g_bs)ns=g_bs;
    WaitForSingleObject(g_ev,2000);g_nd=0;
    for(long c=0;c<g_ch;c++){float*d=(float*)g_b[c];for(long i=0;i<ns;i++)d[i]=sr[i*g_ch+c];}
    VC(g_a,VI_OUTRDY,ASErr)(g_a);PyBuffer_Release(&v);Py_RETURN_TRUE;}

static PyObject* asio_close(PyObject*s,PyObject*a){
    if(!g_a)Py_RETURN_FALSE;
    VC(g_a,VI_STOP,ASErr)(g_a);VC(g_a,VI_DISPBUF,ASErr)(g_a);VC(g_a,2,unsigned long)(g_a);
    if(g_ev){CloseHandle(g_ev);g_ev=NULL;}free(g_b);g_b=NULL;g_a=NULL;g_ch=g_bs=0;Py_RETURN_TRUE;}

static PyObject* asio_set_rate(PyObject*s,PyObject*a){
    const char*cs;double r;if(!PyArg_ParseTuple(a,"sd",&cs,&r))return NULL;
    CoInitializeEx(NULL,2);CLSID c=mkclsid(cs);void*p=NULL;
    if(FAILED(CoCreateInstance(&c,NULL,CLSCTX_INPROC_SERVER,(IID*)&c,&p))||!p)Py_RETURN_FALSE;
    VC(p,VI_INIT,long,void*)(p,NULL);VC(p,VI_SETRATE,ASErr,double)(p,r);VC(p,2,unsigned long)(p);Py_RETURN_TRUE;}

static PyObject* asio_get_rates(PyObject*s,PyObject*a){
    const char*cs;if(!PyArg_ParseTuple(a,"s",&cs))return NULL;
    CoInitializeEx(NULL,2);CLSID c=mkclsid(cs);void*p=NULL;
    if(FAILED(CoCreateInstance(&c,NULL,CLSCTX_INPROC_SERVER,(IID*)&c,&p))||!p)return PyList_New(0);
    VC(p,VI_INIT,long,void*)(p,NULL);PyObject*l=PyList_New(0);
    double rs[]={44100,48000,88200,96000,176400,192000,352800,384000};
    for(int i=0;i<8;i++)if(VC(p,VI_CANRATE,ASErr,double)(p,rs[i])==0)PyList_Append(l,PyLong_FromLong((long)rs[i]));
    VC(p,2,unsigned long)(p);return l;}

static PyMethodDef M[]={
    {"open",asio_open,METH_VARARGS,"Open ASIO device and start streaming."},
    {"write",asio_write,METH_VARARGS,"Write interleaved float32 PCM."},
    {"close",asio_close,METH_VARARGS,"Close ASIO device."},
    {"set_rate",asio_set_rate,METH_VARARGS,"Quick rate set."},
    {"get_rates",asio_get_rates,METH_VARARGS,"Get supported rates."},{NULL}};
static struct PyModuleDef md={PyModuleDef_HEAD_INIT,"asio_ext",NULL,-1,M};
PyMODINIT_FUNC PyInit_asio_ext(void){return PyModule_Create(&md);}
